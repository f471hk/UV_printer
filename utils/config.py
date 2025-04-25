# utils/config.py
"""
Configuration constants for the experiment control script.
"""
import os # Needed for joining paths

# --- General ---
# Directory for all output files (logs, coords, images)
OUTPUT_DIR = "output"

# --- Path Generation Config ---
SOURCE_IMAGE_PATH = "input/2x2grid.jpg" # Image to generate path from
PATH_GEN_STEP_SIZE = 50.0       # Scaling factor (e.g., um per pixel) used by Path Generator
# Define the *exact* filename the path generator will create
GENERATED_COORD_FILENAME = "generated_coords_tsp.txt"
# Combine output dir and filename for the path generator's output
COORDINATE_FILE_PATH = os.path.join(OUTPUT_DIR, GENERATED_COORD_FILENAME)

# --- Motion System Config ---
X_STAGE_SERIAL = 27269534
Y_STAGE_SERIAL = 27269887
# Conversion factor for motion system (e.g., steps per um)
# IMPORTANT: This needs to relate correctly to PATH_GEN_STEP_SIZE
# If PATH_GEN_STEP_SIZE is um/pixel and coords are in um, then DIST_PER_STEP should be steps/um.
DIST_PER_STEP = 34.600

# --- UV Controller Config ---
UV_COM_PORT = "COM3"
UV_BAUDRATE = 9600

# --- Experiment Runner Config ---
DEFAULT_CURE_TIME_S = 3.0

# --- Logging Config ---
LOG_LEVEL = "INFO"
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'

# --- Internal Timing Estimates ---
UV_COMMAND_OVERHEAD_S = 1.0
MOVE_PROCESS_OVERHEAD_S = 0.5