# utils/experiment_runner.py
"""
Contains the ExperimentRunner class which orchestrates the UV curing
experiment using motion and UV controller components.
"""

import time
import numpy as np
import logging
import sys
import os

# --- Import components from within the 'utils' package ---
# Use relative imports since this module is inside the 'utils' package
from . import config  # Access configuration constants
from .helpers import seconds_to_hms
from .uv_controller import UVcontroller
from .motion_system import MotionSystem

class ExperimentRunner:
    """
    Orchestrates the motion and UV curing experiment based on coordinates from a file.
    Uses MotionSystem and UVcontroller classes provided during initialization.
    """
    # Content is identical to the ExperimentRunner class from the previous
    # main_experiment.py, just pasted here with updated relative imports.

    def __init__(self, motion_system: MotionSystem, uv_controller: UVcontroller, input_file: str, cure_time_s: float):
        """
        Initializes the ExperimentRunner.

        Args:
            motion_system (MotionSystem): An instance of the MotionSystem controller.
            uv_controller (UVcontroller): An instance of the UVcontroller.
            input_file (str): Path to the text file containing x, y coordinates.
            cure_time_s (float): Duration for UV cure at each point (in seconds).
        """
        if not isinstance(motion_system, MotionSystem):
            raise TypeError("motion_system must be an instance of MotionSystem")
        if not isinstance(uv_controller, UVcontroller):
            raise TypeError("uv_controller must be an instance of UVcontroller")
        if not isinstance(cure_time_s, (float, int)) or cure_time_s <= 0:
            raise ValueError("cure_time_s must be a positive number.")
        if not isinstance(input_file, str) or not input_file:
             raise ValueError("input_file path must be a non-empty string.")

        self.motion_system = motion_system
        self.uv_controller = uv_controller
        self.input_file = input_file
        self.cure_time_s = float(cure_time_s)
        self.coordinates = None
        self.total_steps = 0
        # Get overhead estimates from config
        self.uv_command_overhead_s = config.UV_COMMAND_OVERHEAD_S
        self.move_process_overhead_s = config.MOVE_PROCESS_OVERHEAD_S
        logging.info("ExperimentRunner initialized.")
        logging.debug(f"Input file: {self.input_file}")
        logging.debug(f"Cure time: {self.cure_time_s}s")

    def load_coordinates(self):
        """Loads coordinate data from the input file."""
        try:
            if not os.path.isfile(self.input_file):
                 logging.error(f"Input file not found at '{self.input_file}'")
                 return False
            logging.info(f"Loading coordinates from: {self.input_file}")
            self.coordinates = np.loadtxt(self.input_file, delimiter=',')
            if self.coordinates.ndim == 1 and self.coordinates.shape[0] >= 2:
                 self.coordinates = self.coordinates.reshape(1, -1)
                 logging.debug("Reshaped single row data to 2D array.")
            if self.coordinates.ndim != 2 or self.coordinates.shape[1] < 2:
                raise ValueError(f"Input file must contain at least two columns (X, Y). Found shape: {self.coordinates.shape}")
            self.total_steps = len(self.coordinates)
            if self.total_steps == 0:
                 logging.warning("Coordinate file loaded successfully but contains no data points.")
                 return False
            logging.info(f"Successfully loaded {self.total_steps} coordinate pairs.")
            return True
        except FileNotFoundError:
            logging.error(f"Error: Input file disappeared before loading at '{self.input_file}'")
            self.coordinates = None; self.total_steps = 0
            return False
        except ValueError as e:
             logging.error(f"Error parsing coordinate file '{self.input_file}': {e}", exc_info=False)
             self.coordinates = None; self.total_steps = 0
             return False
        except Exception as e:
            logging.error(f"Unexpected error loading coordinate file '{self.input_file}': {e}", exc_info=True)
            self.coordinates = None; self.total_steps = 0
            return False

    def estimate_duration(self):
        """Estimates and prints the total experiment duration."""
        if self.total_steps <= 0:
            logging.warning("Cannot estimate duration: No coordinates loaded or file is empty.")
            return 0
        total_seconds = (self.total_steps * (self.cure_time_s + self.move_process_overhead_s)) \
                      + self.uv_command_overhead_s + self.uv_command_overhead_s
        hours, minutes, seconds = seconds_to_hms(total_seconds) # Use helper
        logging.info(f"Estimated total steps: {self.total_steps}")
        logging.info(f"Cure time per step: {self.cure_time_s}s")
        logging.info(f"Estimated overheads (UV command, Move/Process): {self.uv_command_overhead_s}s, {self.move_process_overhead_s}s")
        logging.info(f"Estimated total duration: ~{total_seconds:.0f} seconds ({hours}h {minutes}m {seconds}s)")
        return total_seconds

    def _connect_hardware(self):
        """Connects to both motion system and UV controller."""
        logging.info("Connecting to hardware...")
        motion_ok = self.motion_system.connect()
        if not motion_ok:
             logging.error("Experiment aborted: Failed to connect motion system.")
             return False
        uv_ok = self.uv_controller.connect()
        if not uv_ok:
             logging.error("Experiment aborted: Failed to connect UV controller.")
             self.motion_system.disconnect() # Clean up motion system
             return False
        if not self.motion_system.is_connected() or not self.uv_controller.is_connected():
             logging.critical("Hardware connection check failed after connect calls! Aborting.")
             self.uv_controller.disconnect()
             self.motion_system.disconnect()
             return False
        logging.info("Hardware connected successfully.")
        return True

    def _disconnect_hardware(self):
        """Disconnects hardware, ensuring UV is turned off first."""
        logging.info("Disconnecting hardware...")
        if self.uv_controller.is_connected():
             logging.info("Turning UV light OFF.")
             off_success = self.uv_controller.uv_off()
             if not off_success: logging.warning("UV OFF command may have failed.")
        else:
             logging.warning("Skipping UV OFF (controller not connected).")
        self.uv_controller.disconnect()
        self.motion_system.disconnect()
        logging.info("Hardware disconnection complete.")

    def run(self, start_at_origin=True):
        """
        Runs the full experiment sequence: connect, loop through points, disconnect.
        Args: start_at_origin (bool): If True, move stages to (0,0) before starting.
        Returns: bool: True if successful, False otherwise.
        """
        logging.info("================ Starting Experiment Run ================")
        run_success_status = False
        try:
            if not self.load_coordinates(): raise RuntimeError("Failed to load coordinates.")
            if not self._connect_hardware(): raise RuntimeError("Failed to connect hardware.")

            self.estimate_duration()
            start_time = time.monotonic()

            if start_at_origin:
                logging.info("Moving to origin (0, 0) before starting...")
                if not self.motion_system.move_to_um(0.0, 0.0):
                    raise RuntimeError("Failed to move to origin position (0,0).")
                logging.info("At origin.")

            logging.info("Turning UV light ON for the duration of the run.")
            if not self.uv_controller.uv_on(): raise RuntimeError("Failed to turn UV light ON.")

            current_step = 0 # Initialize step counter before loop
            for i, row in enumerate(self.coordinates, start=1):
                current_step = i # Update step counter for error reporting
                x_pos, y_pos = row[0], row[1]
                step_start_time = time.monotonic()
                percentage = (i / self.total_steps) * 100
                logging.info(f"--- Step {i}/{self.total_steps} ({percentage:.1f}%) ---")
                logging.info(f"Target Coordinates: (X={x_pos:.3f}, Y={y_pos:.3f})")

                logging.debug(f"Initiating move to X={x_pos:.3f}, Y={y_pos:.3f}...")
                if not self.motion_system.move_to_um(x_pos_um=x_pos, y_pos_um=y_pos):
                    raise RuntimeError(f"Motion system failed during move at step {i}")

                logging.info(f"Starting cure: waiting for {self.cure_time_s:.2f} seconds...")
                time.sleep(self.cure_time_s)
                logging.info("Cure wait finished.")

                step_duration = time.monotonic() - step_start_time
                logging.info(f"Step {i} completed in {step_duration:.2f}s.")

            logging.info(">>>>>>>> All coordinate steps processed successfully. <<<<<<<<")
            run_success_status = True # Mark as successful only if loop completes

        except KeyboardInterrupt:
             logging.warning("Keyboard interrupt detected! Aborting experiment run.")
        except Exception as e:
             # Log error with step number if available
             step_info = f"at step {current_step}" if 'current_step' in locals() and current_step > 0 else "during setup or connection"
             logging.critical(f"A critical error occurred {step_info}: {e}", exc_info=True)
        finally:
            logging.info("Experiment finished or aborted. Executing cleanup sequence...")
            self._disconnect_hardware() # Ensure hardware is always disconnected
            end_time = time.monotonic()
            # Calculate duration only if start_time was defined
            total_run_time = (end_time - start_time) if 'start_time' in locals() else 0
            h, m, s = seconds_to_hms(total_run_time)
            logging.info(f"Total elapsed run time: {total_run_time:.2f}s ({h}h {m}m {s}s).")
            logging.info(f"Experiment overall status: {'SUCCESSFUL' if run_success_status else 'FAILED or ABORTED'}")
            logging.info("================= Experiment Run Ended =================")

        return run_success_status # Return the final status