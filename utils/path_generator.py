# utils/path_generator.py
"""
Contains the ImageTSPOptimizer class to generate optimized coordinate paths
from a binary image using OpenCV and OR-Tools TSP solver.
"""

import cv2
import numpy as np
from scipy.spatial.distance import pdist, squareform
import matplotlib.pyplot as plt
from matplotlib import cm
import os
import logging
import time # Added import

try:
    from ortools.constraint_solver import routing_enums_pb2
    from ortools.constraint_solver import pywrapcp
except ImportError:
    logging.warning("Google OR-Tools library not found. TSP optimization will not work.")
    pywrapcp = None # Placeholder

class ImageTSPOptimizer:
    """
    Generates an optimized path (solving TSP for each component)
    from the white pixels of a binary image.
    """
    # --- CORRECT __init__ METHOD ---
    def __init__(self, image_path: str, output_file_path: str, step_size: float, output_dir: str = "output"):
        """
        Initializes the optimizer.

        Args:
            image_path (str): Path to the source image file.
            output_file_path (str): Path where the generated coordinate file will be saved.
            step_size (float): Scaling factor to convert pixel coordinates to output units (e.g., um).
            output_dir (str): Directory to save visualization images.
        """
        if pywrapcp is None:
            raise RuntimeError("Google OR-Tools library is required but not installed or importable.")

        self.image_path = image_path
        self.output_file_path = output_file_path # Path for the coordinate data
        self.output_dir = output_dir # Path for images/plots
        self.step_size = float(step_size)
        self.img = None
        self.binary = None
        self.labels = None
        self.num_labels = 0
        self.all_paths_pixels = [] # Correct variable name

        os.makedirs(self.output_dir, exist_ok=True)
        output_coord_dir = os.path.dirname(self.output_file_path)
        if output_coord_dir:
            os.makedirs(output_coord_dir, exist_ok=True)

        logging.info(f"ImageTSPOptimizer initialized for image: {self.image_path}")
        logging.info(f"Output coordinate file: {self.output_file_path}")
        logging.info(f"Visualization output directory: {self.output_dir}")
        logging.info(f"Step size (scaling factor): {self.step_size}")

    # --- REST OF THE CLASS METHODS (Load Image, Threshold, etc.) ---
    # (Make sure these are also present and correct as provided before)

    def load_image(self):
        """Loads the image in grayscale."""
        logging.info(f"Loading image: {self.image_path}")
        self.img = cv2.imread(self.image_path, cv2.IMREAD_GRAYSCALE)
        if self.img is None:
            logging.error(f"Image at {self.image_path} could not be loaded.")
            raise FileNotFoundError(f"Image at {self.image_path} could not be loaded.")
        logging.info(f"Image shape: {self.img.shape}")

    def threshold_image(self, threshold_value=128):
        """Applies binary thresholding to the image."""
        logging.info(f"Applying binary threshold with value {threshold_value}.")
        _, self.binary = cv2.threshold(self.img, threshold_value, 255, cv2.THRESH_BINARY)
        white_pixels = np.sum(self.binary == 255)
        logging.info(f"Number of white pixels after thresholding: {white_pixels}")
        if white_pixels == 0:
            logging.warning("No white pixels found after thresholding. Output path will be empty.")

    def identify_shapes(self):
        """Identifies connected components (shapes) in the binary image."""
        logging.info("Identifying connected components...")
        self.num_labels, self.labels = cv2.connectedComponents(self.binary, connectivity=8)
        actual_shapes = self.num_labels - 1
        logging.info(f"Number of connected components found: {actual_shapes}")
        if actual_shapes <= 0:
             logging.warning("No foreground shapes identified.")

    def _solve_tsp_for_coords(self, coords):
        """Solves the TSP for a given list of coordinates."""
        num_coords = len(coords)
        if num_coords <= 1: return coords.tolist()
        if num_coords > 5000: logging.warning(f"Large number of coordinates ({num_coords}) for TSP.")

        logging.debug(f"Solving TSP for {num_coords} coordinates...")
        try:
            manager = pywrapcp.RoutingIndexManager(num_coords, 1, 0)
            routing = pywrapcp.RoutingModel(manager)
            distances = squareform(pdist(coords, metric='euclidean'))
            int_distances = np.round(distances).astype(int)

            def distance_callback(from_index, to_index):
                from_node = manager.IndexToNode(from_index)
                to_node = manager.IndexToNode(to_index)
                if 0 <= from_node < num_coords and 0 <= to_node < num_coords:
                    return int_distances[from_node, to_node]
                else: return 999999

            transit_callback_index = routing.RegisterTransitCallback(distance_callback)
            routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)
            search_parameters = pywrapcp.DefaultRoutingSearchParameters()
            search_parameters.first_solution_strategy = (routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)
            search_parameters.local_search_metaheuristic = (routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH)
            search_parameters.time_limit.seconds = 30
            solution = routing.SolveWithParameters(search_parameters)

            if solution:
                index = routing.Start(0)
                route_indices = []
                while not routing.IsEnd(index):
                    node_index = manager.IndexToNode(index)
                    route_indices.append(node_index)
                    index = solution.Value(routing.NextVar(index))
                ordered_coords = coords[route_indices].tolist()
                logging.debug(f"TSP route length: {len(ordered_coords)} points.")
                return ordered_coords
            else:
                logging.warning("No TSP solution found by OR-Tools.")
                return None
        except Exception as e:
            logging.error(f"Error during TSP solving: {e}", exc_info=True)
            return None

    def process_shapes(self):
        """Processes each identified shape, finds its points, and solves TSP."""
        self.all_paths_pixels = [] # Reset
        if self.labels is None or self.num_labels <= 1:
             logging.warning("No shapes to process.")
             return

        for label_id in range(1, self.num_labels):
            shape_coords_pixels = np.column_stack(np.where(self.labels == label_id))
            if len(shape_coords_pixels) == 0: continue
            logging.info(f"Processing shape label {label_id} with {len(shape_coords_pixels)} pixels...")
            optimized_path_pixels = self._solve_tsp_for_coords(shape_coords_pixels)
            if optimized_path_pixels:
                logging.info(f"TSP solution found for shape {label_id}. Path length: {len(optimized_path_pixels)}")
                self.all_paths_pixels.extend(optimized_path_pixels)
            else:
                logging.warning(f"Could not find TSP solution for shape {label_id}. Skipping.")
        logging.info(f"Finished processing shapes. Total points in path: {len(self.all_paths_pixels)}")

    def save_optimized_path(self):
        """Saves the final ordered path coordinates, scaled by the step size."""
        if not self.all_paths_pixels:
             logging.warning("No path data generated. Skipping saving coordinate file.")
             return False

        logging.info(f"Saving scaled optimized path ({len(self.all_paths_pixels)} points) to: {self.output_file_path}")
        try:
            with open(self.output_file_path, "w") as f:
                for point in self.all_paths_pixels:
                    scaled_y = point[0] * self.step_size # row -> y
                    scaled_x = point[1] * self.step_size # col -> x
                    f.write(f"{scaled_x:.3f},{scaled_y:.3f}\n")
            logging.info(f"Optimized path coordinates saved successfully.")
            return True
        except IOError as e:
            logging.error(f"Failed to write coordinate file {self.output_file_path}: {e}")
            return False
        except Exception as e:
             logging.error(f"An unexpected error occurred saving coordinates: {e}", exc_info=True)
             return False

    def visualize_optimized_path(self):
        """Creates and saves a plot visualizing the optimized path order."""
        if not self.all_paths_pixels: return
        logging.info("Generating path visualization plot...")
        try:
            x_coords = [point[1] for point in self.all_paths_pixels]
            y_coords = [point[0] for point in self.all_paths_pixels]
            plt.figure(figsize=(10, 10 * self.img.shape[0]/self.img.shape[1] if self.img is not None else 10))
            plt.plot(x_coords, y_coords, linestyle='-', linewidth=0.8, alpha=0.6, color='gray', label='Path')
            scatter = plt.scatter(x_coords, y_coords, c=range(len(self.all_paths_pixels)), cmap='viridis', s=15, zorder=5, label='Points')
            plt.colorbar(scatter, label='Order of Visit')
            plt.gca().invert_yaxis()
            plt.title('Optimized Visiting Path Order')
            plt.xlabel('X Coordinate (Column Index)')
            plt.ylabel('Y Coordinate (Row Index)')
            plt.axis('equal'); plt.legend(); plt.grid(True, linestyle=':', alpha=0.5)
            plot_file = os.path.join(self.output_dir, "optimized_path_plot.png")
            plt.savefig(plot_file, dpi=300)
            logging.info(f"Path visualization plot saved to {plot_file}")
            plt.close()
        except Exception as e:
             logging.error(f"Failed to generate or save path plot: {e}", exc_info=True)

    def save_optimized_image(self):
        """Creates and saves an image visualizing the path on the original shape."""
        if not self.all_paths_pixels or self.img is None: return
        logging.info("Generating optimized path image visualization...")
        try:
            optimized_img = cv2.cvtColor(self.img, cv2.COLOR_GRAY2BGR)
            optimized_img[self.binary == 0] = optimized_img[self.binary == 0] // 2 # Dim background
            color_map = cm.viridis
            num_points = len(self.all_paths_pixels)
            path_pts = np.array([[p[1], p[0]] for p in self.all_paths_pixels], dtype=np.int32)
            cv2.polylines(optimized_img, [path_pts], isClosed=False, color=(100, 100, 100), thickness=1, lineType=cv2.LINE_AA)
            for idx, point in enumerate(self.all_paths_pixels):
                color = color_map(idx / max(1, num_points - 1))
                color_bgr = (int(color[2] * 255), int(color[1] * 255), int(color[0] * 255))
                cv2.circle(optimized_img, (point[1], point[0]), radius=1, color=color_bgr, thickness=-1)
            output_image_file = os.path.join(self.output_dir, "optimized_path_image.png")
            cv2.imwrite(output_image_file, optimized_img)
            logging.info(f"Optimized path image visualization saved to {output_image_file}")
        except Exception as e:
             logging.error(f"Failed to generate or save optimized path image: {e}", exc_info=True)

    def run(self):
        """Executes the full path generation pipeline."""
        logging.info("Starting image-based path generation pipeline...")
        start_time = time.monotonic()
        try:
            self.load_image()
            self.threshold_image()
            self.identify_shapes()
            self.process_shapes()
            success = self.save_optimized_path() # Save coordinates
            self.visualize_optimized_path() # Visualize
            self.save_optimized_image()     # Visualize
            end_time = time.monotonic()
            logging.info(f"Path generation pipeline finished in {end_time - start_time:.2f} seconds.")
            return success # Return status based on saving coordinates
        except FileNotFoundError as e:
             logging.error(f"Pipeline failed: {e}")
             return False
        except Exception as e:
            logging.error(f"Pipeline failed: {e}", exc_info=True)
            return False

    # --- End of ImageTSPOptimizer Class ---

# (Optional standalone test block remains the same)
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.info("Testing ImageTSPOptimizer standalone...")
    test_image = "test_image.png"
    test_output_dir = "output_test_pathgen"
    test_output_coords = os.path.join(test_output_dir, "generated_test_coords.txt")
    test_step_size = 10.0
    if not os.path.exists(test_image):
         logging.info(f"Creating dummy test image: {test_image}")
         dummy_img = np.zeros((100, 150), dtype=np.uint8)
         cv2.rectangle(dummy_img, (20, 30), (50, 60), 255, -1)
         cv2.circle(dummy_img, (100, 50), 20, 255, -1)
         cv2.imwrite(test_image, dummy_img)
    try:
        optimizer = ImageTSPOptimizer(image_path=test_image, output_file_path=test_output_coords, step_size=test_step_size, output_dir=test_output_dir)
        optimizer.run()
    except ImportError: logging.error("OR-Tools not installed.")
    except Exception as ex: logging.error(f"Error during standalone test: {ex}", exc_info=True)
    logging.info("ImageTSPOptimizer standalone test finished.")