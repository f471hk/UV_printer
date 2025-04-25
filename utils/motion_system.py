# utils/motion_system.py
"""
Class definition for controlling a 2-axis Thorlabs Kinesis motion system
using pylablib.
"""

import logging
try:
    from pylablib.devices import Thorlabs
except ImportError:
    # Allow code to be imported even if pylablib is not installed,
    # but fail gracefully if used.
    logging.warning("pylablib library not found. MotionSystem control will not work.")
    Thorlabs = None # Placeholder

class MotionSystem:
    """
    Controls a 2-axis Thorlabs Kinesis motion system (e.g., KDC101).
    """
    def __init__(self, x_serial, y_serial, dist_per_step):
        """
        Initializes the MotionSystem controller.

        Args:
            x_serial (int | str): Serial number for the X-axis controller.
            y_serial (int | str): Serial number for the Y-axis controller.
            dist_per_step (float): Conversion factor between desired position units
                                   (e.g., micrometers) and motor steps.
        """
        if Thorlabs is None:
            raise RuntimeError("pylablib library is required but not installed.")

        self.x_serial = str(x_serial)
        self.y_serial = str(y_serial)
        self.dist_per_step = float(dist_per_step)
        if self.dist_per_step == 0:
            # Prevent division by zero later
            raise ValueError("dist_per_step cannot be zero.")

        self.stage_x = None
        self.stage_y = None
        self._is_connected = False
        logging.debug(f"MotionSystem instance created for X:{self.x_serial}, Y:{self.y_serial}")

    def connect(self):
        """Connects to the Thorlabs KDC101 controllers."""
        if self._is_connected:
            logging.warning("Motion system already connected.")
            return True
        try:
            logging.info(f"Connecting to X stage ({self.x_serial})...")
            # Ensure Thorlabs module was imported successfully
            if not Thorlabs: raise RuntimeError("pylablib not loaded.")
            self.stage_x = Thorlabs.KinesisMotor(self.x_serial)
            logging.info(f"Connecting to Y stage ({self.y_serial})...")
            self.stage_y = Thorlabs.KinesisMotor(self.y_serial)
            # Optional: Check device status or perform homing if needed after connect
            # self.stage_x.wait_for_status() # Example, check pylablib docs
            # self.stage_y.wait_for_status()
            self._is_connected = True
            logging.info("Motion system connected successfully.")
            return True
        # Catch specific pylablib/hardware exceptions if known, otherwise general Exception
        except Exception as e:
            logging.error(f"Failed to connect to motion stages (X:{self.x_serial}, Y:{self.y_serial}): {e}", exc_info=False)
            # Attempt to close partially opened connections if possible
            if self.stage_x: self.stage_x.close()
            if self.stage_y: self.stage_y.close()
            self.stage_x = None
            self.stage_y = None
            self._is_connected = False
            return False

    def disconnect(self):
        """Disconnects from the Thorlabs controllers."""
        if not self._is_connected:
            logging.warning("Motion system already disconnected.")
            return
        logging.info("Disconnecting motion system...")
        try:
            if self.stage_x:
                self.stage_x.close()
                logging.info(f"X stage ({self.x_serial}) disconnected.")
            if self.stage_y:
                self.stage_y.close()
                logging.info(f"Y stage ({self.y_serial}) disconnected.")
        except Exception as e:
            # Log error but continue attempt to clear state
            logging.error(f"Error during motion system disconnection: {e}", exc_info=False)
        finally:
            # Ensure state reflects disconnection regardless of errors
            self.stage_x = None
            self.stage_y = None
            self._is_connected = False
            logging.info("Motion system disconnection process finished.")

    def is_connected(self):
        """Returns True if the stages appear connected, False otherwise."""
        # Basic check, pylablib might have more robust internal status checks
        return self._is_connected and self.stage_x is not None and self.stage_y is not None

    def move_to_um(self, x_pos_um, y_pos_um):
        """
        Moves the stages to the specified positions in defined units (e.g., um).

        Args:
            x_pos_um (float): Target X position in defined units.
            y_pos_um (float): Target Y position in defined units.

        Returns:
            bool: True if move command was successful and waited for, False otherwise.
        """
        if not self.is_connected():
            logging.error("Cannot move stages: Motion system not connected.")
            return False
        try:
            target_x_steps = x_pos_um * self.dist_per_step
            target_y_steps = y_pos_um * self.dist_per_step
            logging.debug(f"Moving to (X_um={x_pos_um:.2f}, Y_um={y_pos_um:.2f}) -> (X_steps={target_x_steps:.2f}, Y_steps={target_y_steps:.2f})")

            # Initiate moves (pylablib might handle these sequentially or allow async)
            self.stage_x.move_to(target_x_steps)
            self.stage_y.move_to(target_y_steps)

            # Wait for both moves to complete
            logging.debug("Waiting for X stage move completion...")
            self.stage_x.wait_move() # Check pylablib docs for wait arguments (timeout etc)
            logging.debug("X stage move complete.")
            logging.debug("Waiting for Y stage move completion...")
            self.stage_y.wait_move()
            logging.debug("Y stage move complete.")
            logging.info(f"Motion complete at (X_um={x_pos_um:.2f}, Y_um={y_pos_um:.2f})")
            return True
        except Exception as e: # Catch potential pylablib/device errors during move/wait
            logging.error(f"Error during stage movement or wait: {e}", exc_info=True)
            # Consider attempting to stop motors here if applicable
            # self.stage_x.stop()
            # self.stage_y.stop()
            return False

    def get_position_um(self):
        """
        Gets the current position of the stages in defined units (e.g., um).

        Returns:
            tuple(float | None, float | None): Current (x, y) position,
                                              or (None, None) if not connected or error.
        """
        if not self.is_connected():
            logging.error("Cannot get position: Motion system not connected.")
            return None, None
        try:
            x_steps = self.stage_x.get_position()
            y_steps = self.stage_y.get_position()
            # Use max(..., 1e-12) to prevent division by zero if dist_per_step was allowed to be 0
            x_um = x_steps / self.dist_per_step
            y_um = y_steps / self.dist_per_step
            logging.debug(f"Current position: (X_um={x_um:.2f}, Y_um={y_um:.2f})")
            return x_um, y_um
        except Exception as e:
            logging.error(f"Error getting stage position: {e}", exc_info=False)
            return None, None

    def home(self, wait=True):
        """
        Commands both stages to move to the home position.

        Args:
            wait (bool): If True, wait for the homing sequence to complete.

        Returns:
            bool: True if homing command was sent successfully, False otherwise.
                  Note: Success here doesn't guarantee homing finished if wait=False.
        """
        if not self.is_connected():
            logging.error("Cannot home stages: Motion system not connected.")
            return False
        try:
            logging.info("Starting homing sequence for X and Y stages...")
            self.stage_x.home()
            self.stage_y.home()
            if wait:
                logging.debug("Waiting for X stage homing...")
                self.stage_x.wait_move() # Or wait_home if available
                logging.debug("Waiting for Y stage homing...")
                self.stage_y.wait_move() # Or wait_home if available
                logging.info("Homing sequence complete.")
            else:
                 logging.info("Homing sequence initiated (waiting disabled).")
            return True
        except Exception as e:
            logging.error(f"Error during homing sequence: {e}", exc_info=True)
            return False

# Example usage block (optional)
if __name__ == '__main__':
    # Requires config to be importable or hardcode test values
    try:
        from config import X_STAGE_SERIAL, Y_STAGE_SERIAL, DIST_PER_STEP
    except ImportError:
        logging.error("Could not import config. Using hardcoded test values.")
        X_STAGE_SERIAL = 27269534 # Replace with your actual test serials
        Y_STAGE_SERIAL = 27269887 # Replace with your actual test serials
        DIST_PER_STEP = 34.600

    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.info("Testing MotionSystem standalone...")

    motion = MotionSystem(x_serial=X_STAGE_SERIAL, y_serial=Y_STAGE_SERIAL, dist_per_step=DIST_PER_STEP)

    if motion.connect():
        logging.info("Connection successful.")
        x, y = motion.get_position_um()
        logging.info(f"Initial position: X={x:.2f}, Y={y:.2f}")

        # Test move (use small values for safety)
        test_x, test_y = 10.0, 5.0
        logging.info(f"Moving to X={test_x}, Y={test_y}...")
        if motion.move_to_um(test_x, test_y):
            x, y = motion.get_position_um()
            logging.info(f"Position after move: X={x:.2f}, Y={y:.2f}")
        else:
            logging.error("Move failed.")

        # Test homing
        logging.info("Homing...")
        if motion.home(wait=True):
             x, y = motion.get_position_um()
             logging.info(f"Position after homing: X={x:.2f}, Y={y:.2f}")
        else:
            logging.error("Homing failed.")

        motion.disconnect()
    else:
        logging.error("Failed to connect to motion system.")
    logging.info("MotionSystem standalone test finished.")