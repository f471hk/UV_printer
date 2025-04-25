# main_experiment.py
"""
Main entry point script to launch the UV Curing Experiment GUI application.
"""

import sys
import os
import logging

# --- Import GUI Application Class ---
try:
    # Need QApplication and MainWindow from the gui module
    from gui import MainWindow, QApplication
    # Still need config for logging setup if done here
    from utils import config
except ImportError as e:
    # Provide more helpful error message if gui/utils is not found
    print(f"Error importing application components: {e}")
    print("Ensure:")
    print("  1. 'gui.py' and the 'utils' directory exist in the same folder as this script.")
    print("  2. The 'utils' directory contains an '__init__.py' file.")
    print("  3. You have installed all required libraries: pip install PySide6 pyserial numpy pylablib opencv-python scipy ortools matplotlib")
    print("  4. You are running this script from its parent directory (e.g., 'UV_programming').")
    sys.exit(1)
except Exception as ex:
     print(f"An unexpected error occurred during initial imports: {ex}")
     sys.exit(1)


# --- Setup Logging ---
# Use configuration defined in utils.config
log_level_map = {
    "DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARNING": logging.WARNING,
    "ERROR": logging.ERROR, "CRITICAL": logging.CRITICAL
}
# Set desired level here or read from config.LOG_LEVEL
log_level = log_level_map.get(config.LOG_LEVEL.upper(), logging.INFO)
# Define log file path using config.OUTPUT_DIR
log_file_path = os.path.join(config.OUTPUT_DIR, 'experiment_gui.log')

# Ensure output directory exists for log file
# Do this *before* trying to create the FileHandler
try:
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
except OSError as dir_err:
     print(f"Error creating output directory '{config.OUTPUT_DIR}': {dir_err}")
     # Decide if you want to exit or just continue without file logging
     # sys.exit(1) # Exit if directory creation fails


# Configure logging (log to console and file)
log_formatter = logging.Formatter(config.LOG_FORMAT)
root_logger = logging.getLogger()
# Clear existing handlers if any (can be useful if running repeatedly)
for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)
root_logger.setLevel(log_level) # Set level on root logger

# Console Handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
root_logger.addHandler(console_handler)

# File Handler
try:
    # Make sure directory exists before creating handler
    if os.path.isdir(config.OUTPUT_DIR):
        file_handler = logging.FileHandler(log_file_path, mode='a') # Append mode
        file_handler.setFormatter(log_formatter)
        root_logger.addHandler(file_handler)
        logging.info(f"File logging attached to: {log_file_path}")
    else:
        logging.warning(f"Output directory '{config.OUTPUT_DIR}' not found. Skipping file logging.")
except Exception as log_ex:
     # Log to console if file handler fails
     logging.warning(f"Could not attach log file handler to {log_file_path}: {log_ex}")


# --- Main Execution ---
if __name__ == "__main__":
    logging.info("======================================================")
    logging.info("Launching Experiment Control GUI")
    logging.info("======================================================")

    exit_code = 0 # Default to success unless Qt fails catastrophically

    try:
        app = QApplication(sys.argv) # Create the Qt Application instance
        # Optional: Apply global font or style settings to app if desired
        # app.setStyle('Fusion')
        main_window = MainWindow()   # Create your main window instance from gui.py
        main_window.show()           # Show the window
        exit_code = app.exec()       # Start the Qt event loop and wait for exit
        logging.info(f"GUI Application closed with exit code {exit_code}.")

    except Exception as e:
        logging.critical(f"An unexpected error occurred launching or running the GUI: {e}", exc_info=True)
        exit_code = 1 # Indicate failure
    finally:
        logging.info("======================================================")
        logging.info(f"Main Script Exiting with code {exit_code}")
        logging.info("======================================================")
        logging.shutdown() # Ensure logs are flushed
        sys.exit(exit_code) # Exit with the determined code