# gui.py
"""
Provides a styled PySide6 GUI application for the UV Curing Experiment.
Allows image selection (with preview), cure time input, path step size input,
and displays progress. Supports background image and custom styling via QSS.
"""

import sys
import os
import time
import logging

# --- GUI Framework ---
from PySide6.QtCore import (
    Qt, QThread, Signal, Slot, QSize
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QDoubleSpinBox, QProgressBar, QTextEdit, QFileDialog, QMessageBox,
    QSizePolicy, QSpacerItem
)
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QPixmap, QIcon, QFont

# --- Import Backend Logic ---
try:
    from utils import config
    from utils.helpers import seconds_to_hms
    from utils.uv_controller import UVcontroller
    from utils.motion_system import MotionSystem
    from utils.path_generator import ImageTSPOptimizer
    from utils.experiment_runner import ExperimentRunner
except ImportError as e:
    print(f"Critical Error: Failed to import utility modules: {e}")
    print("Ensure 'utils' package is accessible and all dependencies are installed.")
    sys.exit(1)

# --- Worker Thread Definition ---

class ExperimentWorker(QThread):
    """
    Runs the path generation and experiment execution in a separate thread.
    Emits signals to update the GUI.
    """
    progress_update = Signal(int, str, str)
    finished = Signal(bool, str)

    # Modified __init__ to accept step_size
    def __init__(self, image_path, cure_time, step_size, parent=None): # Added step_size
        super().__init__(parent)
        self.image_path = image_path
        self.cure_time = cure_time
        self.step_size = step_size # Store the step size from GUI
        self._is_running = True
        self._abort_requested = False
        self.runner = None

    def run(self):
        """The main logic executed in the separate thread."""
        overall_success = False
        final_message = "Process started..."
        motion_ctrl = None
        uv_ctrl = None

        try:
            # --- Phase 1: Path Generation ---
            self.emit_progress(0, "Initializing path generator...", "--:--:--")
            if self._abort_requested: raise InterruptedError("Aborted before path generation")

            # Use self.step_size passed from GUI when creating optimizer
            path_optimizer = ImageTSPOptimizer(
                image_path=self.image_path,
                output_file_path=config.COORDINATE_FILE_PATH,
                step_size=self.step_size, # Use instance variable here
                output_dir=config.OUTPUT_DIR
            )
            path_gen_success = path_optimizer.run()

            if not path_gen_success:
                raise RuntimeError("Path generation failed. Check logs for details.")
            if self._abort_requested: raise InterruptedError("Aborted after path generation")

            self.emit_progress(10, f"Path generated: {config.COORDINATE_FILE_PATH}", "--:--:--")

            # --- Phase 2: Hardware Initialization & Setup ---
            # (Hardware initialization remains the same)
            self.emit_progress(10, "Initializing hardware controllers...", "--:--:--")
            motion_ctrl = MotionSystem(
                x_serial=config.X_STAGE_SERIAL,
                y_serial=config.Y_STAGE_SERIAL,
                dist_per_step=config.DIST_PER_STEP
            )
            uv_ctrl = UVcontroller(
                port=config.UV_COM_PORT,
                baudrate=config.UV_BAUDRATE
            )
            self.emit_progress(15, "Initializing experiment runner...", "--:--:--")
            self.runner = ExperimentRunner(
                motion_system=motion_ctrl,
                uv_controller=uv_ctrl,
                input_file=config.COORDINATE_FILE_PATH,
                cure_time_s=self.cure_time # Use cure_time passed to worker
            )

            # --- Phase 3: Experiment Execution (Managed Step-by-Step) ---
            # (Rest of the run method remains the same as before)
            self.emit_progress(15, "Loading coordinates...", "--:--:--")
            if not self.runner.load_coordinates(): raise RuntimeError("Failed to load generated coordinates.")
            total_steps = self.runner.total_steps
            if total_steps == 0: raise RuntimeError("Loaded coordinate file is empty.")
            estimated_total_seconds = self.runner.estimate_duration(); h,m,s = seconds_to_hms(estimated_total_seconds); est_total_str = f"{h:02d}:{m:02d}:{s:02d}"
            self.emit_progress(15, f"Estimated total duration: ~{est_total_str}", est_total_str)

            self.emit_progress(20, "Connecting hardware...", est_total_str)
            if self._abort_requested: raise InterruptedError("Aborted before hardware connect")
            if not self.runner._connect_hardware(): raise RuntimeError("Failed to connect hardware.")

            start_at_origin = True
            if start_at_origin:
                 self.emit_progress(25, "Moving to origin...", est_total_str)
                 if self._abort_requested: raise InterruptedError("Aborted before homing")
                 if not self.runner.motion_system.move_to_um(0.0, 0.0): raise RuntimeError("Failed to move to origin.")

            self.emit_progress(30, "Turning UV ON...", est_total_str)
            if self._abort_requested: raise InterruptedError("Aborted before UV ON")
            if not self.runner.uv_controller.uv_on(): raise RuntimeError("Failed to turn UV light ON.")

            logging.info(f"Starting experiment loop: {total_steps} steps.")
            run_start_time = time.monotonic()
            for i, row in enumerate(self.runner.coordinates, start=1):
                if self._abort_requested: raise InterruptedError("Experiment aborted by user.")
                step_start_time = time.monotonic()
                x_pos, y_pos = row[0], row[1]
                percentage = int((i / total_steps) * 100)
                current_status = f"Running Step {i}/{total_steps} (X={x_pos:.2f}, Y={y_pos:.2f})"
                remaining_steps = total_steps - i; elapsed_time = time.monotonic() - run_start_time
                avg_step_time = elapsed_time / i if i > 0 else estimated_total_seconds / max(1, total_steps)
                estimated_remaining_sec = remaining_steps * avg_step_time
                rh, rm, rs = seconds_to_hms(estimated_remaining_sec); remaining_str = f"{rh:02d}:{rm:02d}:{rs:02d}"
                self.emit_progress(percentage, current_status, remaining_str)
                if not self.runner.motion_system.move_to_um(x_pos_um=x_pos, y_pos_um=y_pos): raise RuntimeError(f"Motion failed step {i}")
                time.sleep(self.runner.cure_time_s) # Cure wait
                step_duration = time.monotonic() - step_start_time
                logging.info(f"Worker: Step {i} completed in {step_duration:.2f}s")
            overall_success = True; final_message = "Experiment completed successfully."
            self.emit_progress(100, final_message, "00:00:00")
        except InterruptedError as ie: final_message = f"Process Aborted: {ie}"; logging.warning(final_message); overall_success = False
        except Exception as e: final_message = f"Error during execution: {e}"; logging.critical(f"Worker thread failed: {final_message}", exc_info=True); overall_success = False; self.emit_progress(0, f"ERROR: {final_message}", "--:--:--")
        finally:
            logging.info("Worker thread entering finally block for cleanup.")
            self.emit_progress(0, "Cleaning up hardware connections...", "00:00:00")
            if self.runner: self.runner._disconnect_hardware()
            elif uv_ctrl or motion_ctrl: logging.warning("Attempting fallback hardware disconnect..."); (uv_ctrl.disconnect() if uv_ctrl else None); (motion_ctrl.disconnect() if motion_ctrl else None)
            logging.info("Worker thread cleanup finished.")
            self.finished.emit(overall_success, final_message)
            self._is_running = False

    def stop(self):
        logging.info("Worker thread stop requested.")
        self._abort_requested = True

    def emit_progress(self, percentage, status, remaining):
        if self._is_running:
             self.progress_update.emit(percentage, status, remaining)


# --- Main GUI Window ---

class MainWindow(QWidget):
    IMAGE_PREVIEW_SIZE = QSize(200, 200)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("UV Curing Experiment Control")
        self.setGeometry(100, 100, 750, 650) # Increased height slightly for new input
        self.setAcceptDrops(True)
        self.setObjectName("MainWindow")

        self.worker_thread = None
        self.selected_image_path = config.SOURCE_IMAGE_PATH
        self.default_pixmap = QPixmap(config.SOURCE_IMAGE_PATH)
        if self.default_pixmap.isNull():
             logging.warning(f"Default image not found or invalid: {config.SOURCE_IMAGE_PATH}")
             self.default_pixmap = None

        self._init_ui()
        self._connect_signals()
        self._apply_styles()

        self.update_status("Application loaded. Drag/drop image or browse.")
        if self.selected_image_path and os.path.exists(self.selected_image_path):
            self.update_status(f"Default image loaded: {os.path.basename(self.selected_image_path)}")
            self._update_image_preview(self.selected_image_path)
        else: self.update_status("No default image found. Please select an image.")
        self.update_status(f"Default cure time: {self.cure_time_spinbox.value()}s")
        self.update_status(f"Default path step size: {self.step_size_spinbox.value()} units/pixel") # Log default


    def _init_ui(self):
        """Create and arrange UI widgets."""
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(15)

        top_layout = QHBoxLayout(); top_layout.setSpacing(20)
        input_controls_layout = QVBoxLayout()
        file_input_layout = QHBoxLayout()
        # Group parameter inputs together
        param_layout = QHBoxLayout(); param_layout.setSpacing(15) # Layout for Cure Time and Step Size
        cure_time_layout = QVBoxLayout() # Vertical layout for cure time label+input
        step_size_layout = QVBoxLayout() # Vertical layout for step size label+input

        button_layout = QHBoxLayout()
        progress_info_layout = QHBoxLayout()
        status_layout = QVBoxLayout()

        # --- Widgets ---
        self.file_label = QLabel("Source Image:")
        self.file_path_edit = QLineEdit(os.path.basename(self.selected_image_path) if self.selected_image_path else "No image selected")
        self.file_path_edit.setReadOnly(True); self.file_path_edit.setPlaceholderText("Drag & Drop Image Here or Browse...")
        self.browse_button = QPushButton("Browse..."); self.browse_button.setIcon(QIcon.fromTheme("document-open", QIcon("icons/folder-open.png")))

        self.image_preview_label = QLabel("Image Preview"); self.image_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview_label.setFixedSize(self.IMAGE_PREVIEW_SIZE); self.image_preview_label.setObjectName("ImagePreviewLabel")

        # Cure Time Widgets
        self.cure_time_label = QLabel("Curing Time (s):")
        self.cure_time_spinbox = QDoubleSpinBox(); self.cure_time_spinbox.setRange(0.1, 3600.0); self.cure_time_spinbox.setValue(config.DEFAULT_CURE_TIME_S)
        self.cure_time_spinbox.setDecimals(1); self.cure_time_spinbox.setSingleStep(0.1); self.cure_time_spinbox.setToolTip("UV cure time per point in seconds")

        # --- New: Path Step Size Widgets ---
        self.step_size_label = QLabel("Path Step Size (units/px):")
        self.step_size_spinbox = QDoubleSpinBox() # Using DoubleSpinBox for consistency
        self.step_size_spinbox.setRange(0.1, 5000.0) # Set a reasonable range
        self.step_size_spinbox.setValue(config.PATH_GEN_STEP_SIZE) # Default from config
        self.step_size_spinbox.setDecimals(1) # Allow decimals
        self.step_size_spinbox.setSingleStep(10) # Set step increment to 10
        self.step_size_spinbox.setToolTip("Scaling factor for path generation (e.g., um per pixel). Step buttons change by 10.")
        # --- End New Widgets ---

        self.start_button = QPushButton(" START EXPERIMENT"); self.start_button.setIcon(QIcon.fromTheme("media-playback-start", QIcon("icons/play.png"))); self.start_button.setObjectName("StartButton")
        self.stop_button = QPushButton(" STOP EXPERIMENT"); self.stop_button.setIcon(QIcon.fromTheme("media-playback-stop", QIcon("icons/stop.png"))); self.stop_button.setEnabled(False); self.stop_button.setObjectName("StopButton")

        self.progress_bar = QProgressBar(); self.progress_bar.setRange(0, 100); self.progress_bar.setValue(0); self.progress_bar.setTextVisible(True); self.progress_bar.setFormat("%p%")
        self.est_total_label = QLabel("Est. Total: --:--:--"); self.est_remaining_label = QLabel("Est. Remaining: --:--:--")

        self.status_label = QLabel("Status / Log:"); self.status_box = QTextEdit(); self.status_box.setReadOnly(True); self.status_box.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth); self.status_box.setObjectName("StatusBox"); self.status_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # --- Assemble Layout ---
        file_input_layout.addWidget(self.file_label); file_input_layout.addWidget(self.file_path_edit, 1); file_input_layout.addWidget(self.browse_button)
        input_controls_layout.addLayout(file_input_layout)

        # Parameter Layout (Cure Time + Step Size side-by-side)
        cure_time_layout.addWidget(self.cure_time_label)
        cure_time_layout.addWidget(self.cure_time_spinbox)
        param_layout.addLayout(cure_time_layout)

        step_size_layout.addWidget(self.step_size_label)
        step_size_layout.addWidget(self.step_size_spinbox)
        param_layout.addLayout(step_size_layout)

        param_layout.addStretch(1) # Push params to the left
        input_controls_layout.addLayout(param_layout) # Add the parameter row
        input_controls_layout.addSpacerItem(QSpacerItem(20, 10, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        top_layout.addLayout(input_controls_layout, 2); top_layout.addWidget(self.image_preview_label, 1)
        self.main_layout.addLayout(top_layout)

        button_layout.addStretch(1); button_layout.addWidget(self.start_button); button_layout.addWidget(self.stop_button); button_layout.addStretch(1)
        self.main_layout.addLayout(button_layout)

        self.main_layout.addWidget(self.progress_bar)
        progress_info_layout.addWidget(self.est_total_label); progress_info_layout.addStretch(1); progress_info_layout.addWidget(self.est_remaining_label)
        self.main_layout.addLayout(progress_info_layout)

        status_layout.addWidget(self.status_label); status_layout.addWidget(self.status_box, 1)
        self.main_layout.addLayout(status_layout)


    def _connect_signals(self):
        self.browse_button.clicked.connect(self.browse_for_image)
        self.start_button.clicked.connect(self.start_experiment)
        self.stop_button.clicked.connect(self.stop_experiment)

    def _apply_styles(self):
        # (Style sheet definition remains the same as before - ensure background path is correct)
        background_image_path = "images/background.png" # <-- CHANGE THIS PATH if needed
        if not os.path.exists(background_image_path):
             logging.warning(f"Background image not found at: {background_image_path}. Skipping background.")
             background_image_style = ""
        else:
             background_image_path_qss = background_image_path.replace("\\", "/")
             background_image_style = f"""#MainWindow {{ background-image: url({background_image_path_qss}); background-repeat: no-repeat; background-position: center; background-attachment: fixed; }}"""

        style_sheet = f"""
            {background_image_style}
            QWidget {{ font-family: Segoe UI, Arial, sans-serif; font-size: 10pt; color: #E0E0E0; }}
            #MainWindow {{ background-color: #2E2E2E; }}
            QLabel {{ color: #C0C0C0; padding: 2px; background-color: transparent; }}
            QLineEdit {{ background-color: #3E3E3E; border: 1px solid #555555; border-radius: 4px; padding: 5px; color: #FFFFFF; }}
            QLineEdit:read-only {{ background-color: #4A4A4A; color: #AAAAAA; }}
            QDoubleSpinBox {{ background-color: #3E3E3E; border: 1px solid #555555; border-radius: 4px; padding: 4px; color: #FFFFFF; }}
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border; width: 16px; border-left: 1px solid #555555; border-radius: 0px 4px 4px 0px; }}
            /* Add actual icon files or remove image url lines */
            QDoubleSpinBox::up-arrow {{ /* image: url(icons/up-arrow.png); */ height: 7px; width: 7px; }}
            QDoubleSpinBox::down-arrow {{ /* image: url(icons/down-arrow.png); */ height: 7px; width: 7px; }}
            QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{ background-color: #4E4E4E; }}
            QPushButton {{ background-color: #5588EE; color: white; border: none; padding: 8px 16px; border-radius: 4px; min-height: 20px; }}
            QPushButton:hover {{ background-color: #6699FF; }}
            QPushButton:pressed {{ background-color: #4477DD; }}
            QPushButton:disabled {{ background-color: #5A5A5A; color: #AAAAAA; }}
            #StartButton {{ background-color: #55AA55; }} #StartButton:hover {{ background-color: #66BB66; }} #StartButton:pressed {{ background-color: #449944; }}
            #StopButton {{ background-color: #DD5555; }} #StopButton:hover {{ background-color: #EE6666; }} #StopButton:pressed {{ background-color: #CC4444; }}
            QProgressBar {{ border: 1px solid #555555; border-radius: 4px; text-align: center; color: white; background-color: #3E3E3E; }}
            QProgressBar::chunk {{ background-color: QLinearGradient( x1: 0, y1: 0, x2: 1, y2: 0, stop: 0 #55AA55, stop: 1 #66DD66); border-radius: 3px; margin: 1px; }}
            #StatusBox {{ background-color: rgba(40, 40, 40, 0.85); border: 1px solid #4A4A4A; border-radius: 4px; color: #D0D0D0; font-family: Consolas, Courier New, monospace; font-size: 9pt; }}
            #ImagePreviewLabel {{ border: 1px dashed #666666; background-color: rgba(60, 60, 60, 0.7); color: #888888; border-radius: 4px; }}
        """
        self.setStyleSheet(style_sheet)
        # Set tooltips
        self.file_path_edit.setToolTip("Drag & Drop image file here or use Browse")
        self.browse_button.setToolTip("Browse for source image file")
        self.cure_time_spinbox.setToolTip("Set the UV cure time per point in seconds")
        # Add tooltip for new spinbox
        self.step_size_spinbox.setToolTip("Scaling factor for path generation (e.g., um per pixel). Step buttons change by 10.")
        self.start_button.setToolTip("Start the path generation and experiment run")
        self.stop_button.setToolTip("Stop the currently running experiment (after current step)")
        self.image_preview_label.setToolTip("Preview of the selected source image")
        self.status_box.setToolTip("Shows status messages and logs during the process")

    # --- Drag and Drop ---
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
        else: event.ignore()

    def dropEvent(self, event: QDropEvent):
        mime_data = event.mimeData(); urls = mime_data.urls()
        if urls:
            file_path = urls[0].toLocalFile()
            if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff')):
                self._handle_new_image_path(file_path); event.acceptProposedAction(); return
            else: self.update_status(f"Dropped file ignored: Not an image ({os.path.basename(file_path)})")
        event.ignore()

    # --- UI Action Slots ---
    @Slot()
    def browse_for_image(self):
        start_dir = os.path.dirname(self.selected_image_path) if self.selected_image_path else os.getcwd()
        file_dialog = QFileDialog(self, "Select Source Image", start_dir, "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)"); file_dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        if file_dialog.exec():
            filenames = file_dialog.selectedFiles()
            if filenames: self._handle_new_image_path(filenames[0])

    @Slot()
    def start_experiment(self):
        if not self.selected_image_path or not os.path.exists(self.selected_image_path):
            QMessageBox.warning(self, "Input Error", "Please select a valid source image file."); return
        cure_time = self.cure_time_spinbox.value()
        step_size = self.step_size_spinbox.value() # <<< Get step size value
        if cure_time <= 0 or step_size <= 0:
             QMessageBox.warning(self, "Input Error", "Cure time and step size must be positive."); return

        self.update_status(f"Starting experiment: Image='{os.path.basename(self.selected_image_path)}', Cure Time={cure_time}s, Step Size={step_size} units/px")
        self._set_running_state(True)

        # <<< Pass step_size to worker
        self.worker_thread = ExperimentWorker(self.selected_image_path, cure_time, step_size)
        # 2. THEN update the UI state (now self.worker_thread is not None)
        self._set_running_state(True) # This will now correctly enable the Stop button

        self.worker_thread.progress_update.connect(self.handle_progress_update)
        self.worker_thread.finished.connect(self.handle_experiment_finished)
        self.worker_thread.start()

    @Slot()
    def stop_experiment(self):
        if self.worker_thread and self.worker_thread.isRunning():
            self.update_status("STOP requested. Finishing current step and cleaning up...")
            self.worker_thread.stop(); self.stop_button.setEnabled(False)

    # --- Slots to Handle Worker Signals ---
    @Slot(int, str, str)
    def handle_progress_update(self, percentage, status, remaining_time):
        if percentage >= 0: self.progress_bar.setValue(percentage)
        else: self.progress_bar.setValue(0)
        self.update_status(status)
        self.est_remaining_label.setText(f"Est. Remaining: {remaining_time}")
        if "Estimated total duration:" in status:
             try: self.est_total_label.setText(f"Est. Total: {status.split('~')[1].split('s')[0].strip()}")
             except Exception: pass

    @Slot(bool, str)
    def handle_experiment_finished(self, success, final_message):
        self.update_status(f"Process Finished. Status: {'Success' if success else 'Failed/Aborted'} - {final_message}")
        self._set_running_state(False)
        if not success: self.progress_bar.setValue(0); self.est_remaining_label.setText("Est. Remaining: --:--:--"); self.est_total_label.setText("Est. Total: --:--:--")
        self.worker_thread = None

    # --- Helper Methods ---
    def _handle_new_image_path(self, file_path):
        self.selected_image_path = file_path; self.file_path_edit.setText(os.path.basename(file_path)); self.file_path_edit.setToolTip(file_path)
        self.update_status(f"Selected image: {file_path}"); self._update_image_preview(file_path)

    def _update_image_preview(self, file_path):
        pixmap = QPixmap(file_path)
        if pixmap.isNull(): self.image_preview_label.setText("Preview\nNot Available"); self.image_preview_label.setPixmap(QPixmap()); logging.warning(f"Failed to load image preview: {file_path}")
        else: scaled_pixmap = pixmap.scaled(self.IMAGE_PREVIEW_SIZE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation); self.image_preview_label.setPixmap(scaled_pixmap); self.image_preview_label.setText("")

    def _set_running_state(self, is_running):
        self.start_button.setEnabled(not is_running); self.browse_button.setEnabled(not is_running)
        self.cure_time_spinbox.setEnabled(not is_running); self.step_size_spinbox.setEnabled(not is_running) # Disable step size too
        self.stop_button.setEnabled(is_running and self.worker_thread is not None)

    def update_status(self, message):
        logging.info(f"GUI Status: {message}"); timestamp = time.strftime("%H:%M:%S")
        self.status_box.append(f"[{timestamp}] {message}"); self.status_box.verticalScrollBar().setValue(self.status_box.verticalScrollBar().maximum())

    def closeEvent(self, event):
        if self.worker_thread and self.worker_thread.isRunning():
            reply = QMessageBox.question(self, 'Confirm Exit', "Experiment is running. Are you sure you want to exit?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes: self.stop_experiment(); event.accept()
            else: event.ignore()
        else: event.accept()

# --- Standalone Test Block ---
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s [%(filename)s:%(lineno)d] %(message)s')
    app = QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec())