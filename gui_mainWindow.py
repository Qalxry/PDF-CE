import os
import json
import fitz
import logging  # Import logging
from PyQt5.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QLineEdit,
    QFileDialog,
    QSpinBox,
    QSlider,
    QCheckBox,
    QProgressBar,
    QMessageBox,
    QGroupBox,
    QFormLayout,
    QSizePolicy,
    QSplitter,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

from utils import CONFIG_FILE, DEFAULT_SETTINGS
from workers import CompressionWorker
from gui_previewPanel import PreviewPanel
import subprocess
import webbrowser

# Constants
REPO_URL = "https://github.com/Qalxry/PDF-EC"
logger = logging.getLogger(__name__)  # Logger for this module


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        logger.info("MainWindow initializing...")
        # ... (rest of __init__ remains the same) ...
        self.setWindowTitle("PDF Image Compressor & Enhancer")
        self.setGeometry(50, 50, 1300, 800)
        self.settings = DEFAULT_SETTINGS.copy()
        self.compression_thread = None
        self.compression_worker_obj = None
        self.preview_panel = None
        self.init_ui()
        self.load_settings()  # This now also attempts to load preview if path is valid
        logger.info("MainWindow initialized.")

    def init_ui(self):
        logger.debug("MainWindow UI initializing...")
        # ... (rest of init_ui as in previous correct version, with PreviewPanel instantiation) ...
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        overall_layout = QVBoxLayout(self.central_widget)
        settings_panel_widget = QWidget()
        settings_panel_layout = QVBoxLayout(settings_panel_widget)
        settings_panel_layout.setContentsMargins(0, 0, 0, 0)
        io_group = QGroupBox("Input / Output")  # ... (io_group setup)
        io_layout = QFormLayout()
        self.input_path_edit = QLineEdit()
        self.input_path_edit.editingFinished.connect(self.trigger_preview_load_from_input_edit)
        self.output_path_edit = QLineEdit()
        self.browse_input_btn = QPushButton("Browse...")
        self.browse_output_btn = QPushButton("Browse...")
        self.browse_input_btn.clicked.connect(self.select_input_file)
        self.browse_output_btn.clicked.connect(self.select_output_file)
        self.load_preview_btn = QPushButton("Load/Refresh Preview")
        self.load_preview_btn.clicked.connect(self.trigger_preview_load_from_button)
        io_layout.addRow("Input PDF:", self.input_path_edit)
        io_layout.addRow("", self.browse_input_btn)
        io_layout.addRow("Output PDF:", self.output_path_edit)
        io_layout.addRow("", self.browse_output_btn)
        io_layout.addRow(self.load_preview_btn)
        io_group.setLayout(io_layout)
        settings_panel_layout.addWidget(io_group)

        comp_group = QGroupBox("Compression Settings")  # ... (comp_group setup)
        comp_layout = QFormLayout()
        self.dpi_spinbox = QSpinBox()
        self.dpi_spinbox.setRange(50, 600)
        self.dpi_spinbox.setSuffix(" DPI")
        self.quality_slider = QSlider(Qt.Horizontal)
        self.quality_slider.setRange(10, 100)
        self.quality_label = QLabel()
        self.quality_slider.valueChanged.connect(lambda val, lbl=self.quality_label: lbl.setText(f"{val}%"))
        self.grayscale_checkbox = QCheckBox("Convert to Grayscale")
        comp_layout.addRow("Resolution:", self.dpi_spinbox)
        q_hbox = QHBoxLayout()
        q_hbox.addWidget(self.quality_slider)
        q_hbox.addWidget(self.quality_label)
        comp_layout.addRow("JPEG Quality:", q_hbox)
        comp_layout.addRow(self.grayscale_checkbox)
        comp_group.setLayout(comp_layout)
        settings_panel_layout.addWidget(comp_group)

        enhance_group = QGroupBox("Image Enhancement")  # ... (enhance_group setup)
        enhance_layout = QFormLayout()
        self.contrast_checkbox = QCheckBox("Adjust Contrast")
        self.contrast_slider = QSlider(Qt.Horizontal)
        self.contrast_slider.setRange(5, 25)
        self.contrast_label = QLabel()
        self.contrast_slider.valueChanged.connect(
            lambda val, lbl=self.contrast_label: lbl.setText(f"{val / 10.0:.1f}x")
        )
        self.contrast_checkbox.toggled.connect(
            lambda checked, s=self.contrast_slider, l=self.contrast_label: [
                s.setEnabled(checked),
                l.setEnabled(checked),
            ]
        )
        self.brightness_checkbox = QCheckBox("Adjust Brightness")
        self.brightness_slider = QSlider(Qt.Horizontal)
        self.brightness_slider.setRange(5, 25)
        self.brightness_label = QLabel()
        self.brightness_slider.valueChanged.connect(
            lambda val, lbl=self.brightness_label: lbl.setText(f"{val / 10.0:.1f}x")
        )
        self.brightness_checkbox.toggled.connect(
            lambda checked, s=self.brightness_slider, l=self.brightness_label: [
                s.setEnabled(checked),
                l.setEnabled(checked),
            ]
        )
        self.sharpen_checkbox = QCheckBox("Sharpen Image")
        self.binarize_checkbox = QCheckBox("Binarize (Black & White)")
        self.binarize_threshold_spinbox = QSpinBox()
        self.binarize_threshold_spinbox.setRange(1, 254)
        self.binarize_threshold_spinbox.setSuffix(" (0-255)")
        self.binarize_checkbox.toggled.connect(self.binarize_threshold_spinbox.setEnabled)
        self.denoise_checkbox = QCheckBox("Denoise (Median Filter)")
        enhance_layout.addRow(self.contrast_checkbox)
        c_hbox = QHBoxLayout()
        c_hbox.addWidget(self.contrast_slider)
        c_hbox.addWidget(self.contrast_label)
        enhance_layout.addRow("Factor:", c_hbox)
        enhance_layout.addRow(self.brightness_checkbox)
        b_hbox = QHBoxLayout()
        b_hbox.addWidget(self.brightness_slider)
        b_hbox.addWidget(self.brightness_label)
        enhance_layout.addRow("Factor:", b_hbox)
        enhance_layout.addRow(self.sharpen_checkbox)
        enhance_layout.addRow(self.binarize_checkbox)
        enhance_layout.addRow("Binarize Threshold:", self.binarize_threshold_spinbox)
        enhance_layout.addRow(self.denoise_checkbox)
        enhance_group.setLayout(enhance_layout)
        settings_panel_layout.addWidget(enhance_group)

        ocr_group = QGroupBox("Text Recognition (OCR)")  # ... (ocr_group setup)
        ocr_layout = QVBoxLayout()
        self.ocr_checkbox = QCheckBox("Add Searchable Text Layer (Future Feature)")
        self.ocr_checkbox.setEnabled(False)
        self.ocr_checkbox.setStyleSheet("QCheckBox::indicator { background-color: lightgray; }")
        ocr_layout.addWidget(self.ocr_checkbox)
        ocr_layout.addWidget(QLabel("Requires Tesseract or other OCR engine setup."))
        ocr_group.setLayout(ocr_layout)
        settings_panel_layout.addWidget(ocr_group)
        settings_panel_layout.addStretch(1)

        self.preview_panel = PreviewPanel(self)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(settings_panel_widget)
        splitter.addWidget(self.preview_panel)
        splitter.setStretchFactor(0, 35)
        splitter.setStretchFactor(1, 65)
        splitter.setSizes([self.width() // 3, self.width() * 2 // 3])
        overall_layout.addWidget(splitter)

        control_layout = QHBoxLayout()  # ... (control_layout setup)
        self.compress_btn = QPushButton("Start Compression")
        self.reset_btn = QPushButton("Reset Settings")
        self.cancel_btn = QPushButton("Cancel Compression")
        self.cancel_btn.setEnabled(False)
        self.compress_btn.clicked.connect(self.start_compression)
        self.reset_btn.clicked.connect(self.reset_settings)
        self.cancel_btn.clicked.connect(self.cancel_compression)
        control_layout.addWidget(self.reset_btn)
        control_layout.addStretch()
        control_layout.addWidget(self.cancel_btn)
        control_layout.addWidget(self.compress_btn)

        # Make the splitter stretch to fill available vertical space when the window resizes
        overall_layout.setStretch(0, 1)

        overall_layout.addLayout(control_layout)

        self.progress_bar = QProgressBar()  # ... (progress_bar and status_label setup)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.status_label = QLabel("Ready. Select input PDF and settings.")
        self.status_label.setWordWrap(True)
        overall_layout.addWidget(self.progress_bar)
        overall_layout.addWidget(self.status_label)

        self.connect_settings_to_preview()
        self.update_ui_element_states()
        logger.debug("MainWindow UI initialized.")

    def select_input_file(self):
        fname, _ = QFileDialog.getOpenFileName(
            self, "Select Input PDF", self.settings.get("input_path", ""), "PDF Files (*.pdf)"
        )
        if fname:
            self.input_path_edit.setText(fname)
            if not self.output_path_edit.text():  # Suggest output name
                base, ext = os.path.splitext(fname)
                self.output_path_edit.setText(f"{base}_compressed.pdf")
            self.trigger_preview_load_from_button()  # Load preview after selecting file

    def select_output_file(self):
        suggested_path = self.output_path_edit.text()
        if not suggested_path and self.input_path_edit.text():
            base, ext = os.path.splitext(self.input_path_edit.text())
            suggested_path = f"{base}_compressed.pdf"

        fname, _ = QFileDialog.getSaveFileName(self, "Select Output PDF", suggested_path, "PDF Files (*.pdf)")
        if fname:
            if not fname.lower().endswith(".pdf"):
                fname += ".pdf"
            self.output_path_edit.setText(fname)

    def connect_settings_to_preview(self):
        if not self.preview_panel:
            return
        # Compression settings
        self.dpi_spinbox.valueChanged.connect(self.preview_panel.schedule_processed_preview_update)
        self.quality_slider.valueChanged.connect(self.preview_panel.schedule_processed_preview_update)
        self.grayscale_checkbox.stateChanged.connect(self.preview_panel.schedule_processed_preview_update)
        # Enhancement settings
        self.contrast_checkbox.toggled.connect(self.preview_panel.schedule_processed_preview_update)
        self.contrast_slider.valueChanged.connect(self.preview_panel.schedule_processed_preview_update)
        self.brightness_checkbox.toggled.connect(self.preview_panel.schedule_processed_preview_update)
        self.brightness_slider.valueChanged.connect(self.preview_panel.schedule_processed_preview_update)
        self.sharpen_checkbox.stateChanged.connect(self.preview_panel.schedule_processed_preview_update)
        self.binarize_checkbox.toggled.connect(self.preview_panel.schedule_processed_preview_update)
        self.binarize_threshold_spinbox.valueChanged.connect(self.preview_panel.schedule_processed_preview_update)
        self.denoise_checkbox.stateChanged.connect(self.preview_panel.schedule_processed_preview_update)

    def update_ui_element_states(self):
        # Update enable state based on checkboxes
        is_contrast_checked = self.contrast_checkbox.isChecked()
        self.contrast_slider.setEnabled(is_contrast_checked)
        self.contrast_label.setEnabled(is_contrast_checked)

        is_brightness_checked = self.brightness_checkbox.isChecked()
        self.brightness_slider.setEnabled(is_brightness_checked)
        self.brightness_label.setEnabled(is_brightness_checked)

        self.binarize_threshold_spinbox.setEnabled(self.binarize_checkbox.isChecked())

    def reset_settings(self):
        logger.info("Reset settings button clicked.")
        # ... (rest of reset_settings remains the same) ...
        reply = QMessageBox.question(
            self, "Reset Settings", "Reset settings to default?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            logger.info("User confirmed reset to default settings.")
            self.settings = DEFAULT_SETTINGS.copy()
            self.load_settings()
            self.save_settings()
            self.status_label.setText("Settings reset to defaults.")
        else:
            logger.info("User cancelled reset settings.")

    def load_settings(self):
        logger.info("Loading settings from '%s'.", CONFIG_FILE)
        # ... (rest of load_settings remains the same, add logging for errors) ...
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r") as f:
                    loaded_settings = json.load(f)
                    valid_settings = {k: loaded_settings[k] for k in DEFAULT_SETTINGS if k in loaded_settings}
                    self.settings.update(valid_settings)
                    logger.info("Settings loaded successfully.")
            else:
                self.settings = DEFAULT_SETTINGS.copy()
                logger.info("No settings file found at '%s', using defaults.", CONFIG_FILE)
        except Exception as e:
            self.settings = DEFAULT_SETTINGS.copy()
            logger.error("Error loading settings from '%s': %s. Using defaults.", CONFIG_FILE, e, exc_info=True)
            QMessageBox.warning(self, "Settings Error", f"Could not load settings: {e}\nUsing defaults.")
        # ... (apply settings to UI)
        self.input_path_edit.setText(self.settings["input_path"])
        self.output_path_edit.setText(self.settings["output_path"])
        self.dpi_spinbox.setValue(self.settings["dpi"])
        self.quality_slider.setValue(self.settings["quality"])
        self.quality_label.setText(f"{self.settings['quality']}%")
        self.grayscale_checkbox.setChecked(self.settings["grayscale"])
        self.contrast_checkbox.setChecked(self.settings["enhance_contrast"])
        self.contrast_slider.setValue(int(self.settings["contrast_factor"] * 10))
        self.contrast_label.setText(f"{self.settings['contrast_factor']:.1f}x")
        self.brightness_checkbox.setChecked(self.settings["enhance_brightness"])
        self.brightness_slider.setValue(int(self.settings["brightness_factor"] * 10))
        self.brightness_label.setText(f"{self.settings['brightness_factor']:.1f}x")
        self.sharpen_checkbox.setChecked(self.settings["sharpen"])
        self.binarize_checkbox.setChecked(self.settings["binarize"])
        self.binarize_threshold_spinbox.setValue(self.settings["binarize_threshold"])
        self.denoise_checkbox.setChecked(self.settings["denoise"])
        self.update_ui_element_states()
        if self.input_path_edit.text() and os.path.exists(self.input_path_edit.text()):
            logger.debug("Auto-loading preview from settings for: %s", self.input_path_edit.text())
            self.trigger_preview_load_from_button()

    def save_settings(self):
        logger.info("Saving settings to '%s'.", CONFIG_FILE)
        # ... (rest of save_settings remains the same, add logging for errors) ...
        self.settings["input_path"] = self.input_path_edit.text()
        self.settings["output_path"] = self.output_path_edit.text()
        # ... (gather all settings) ...
        self.settings["dpi"] = self.dpi_spinbox.value()
        self.settings["quality"] = self.quality_slider.value()
        self.settings["grayscale"] = self.grayscale_checkbox.isChecked()
        self.settings["enhance_contrast"] = self.contrast_checkbox.isChecked()
        self.settings["contrast_factor"] = self.contrast_slider.value() / 10.0
        self.settings["enhance_brightness"] = self.brightness_checkbox.isChecked()
        self.settings["brightness_factor"] = self.brightness_slider.value() / 10.0
        self.settings["sharpen"] = self.sharpen_checkbox.isChecked()
        self.settings["binarize"] = self.binarize_checkbox.isChecked()
        self.settings["binarize_threshold"] = self.binarize_threshold_spinbox.value()
        self.settings["denoise"] = self.denoise_checkbox.isChecked()
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.settings, f, indent=4)
            logger.info("Settings saved successfully.")
        except Exception as e:
            logger.error("Error saving settings to '%s': %s", CONFIG_FILE, e, exc_info=True)
            QMessageBox.critical(self, "Settings Error", f"Could not save settings: {e}")

    def closeEvent(self, event):
        logger.info("MainWindow closeEvent triggered. Saving settings and cleaning up.")
        self.save_settings()
        if self.preview_panel:
            logger.debug("Closing preview panel document/threads.")
            self.preview_panel.close_current_document()
        if self.compression_thread and self.compression_thread.isRunning():
            logger.info("Compression thread still running, attempting to cancel and quit.")
            self.cancel_compression()
            self.compression_thread.quit()
            if not self.compression_thread.wait(1000):
                logger.warning("Compression thread did not finish gracefully after 1s, terminating.")
                self.compression_thread.terminate()
        logger.info("Exiting application.")
        event.accept()

    def start_compression(self):
        input_file = self.input_path_edit.text()
        output_file = self.output_path_edit.text()
        logger.info("Start compression clicked. Input: '%s', Output: '%s'", input_file, output_file)
        # ... (validation logic) ...
        if not input_file or not os.path.exists(input_file):
            logger.warning("Compression validation failed: Input PDF '%s' not found or not specified.", input_file)
            QMessageBox.warning(self, "Input Error", "Valid input PDF required.")
            return
        if not output_file:
            logger.warning("Compression validation failed: Output PDF path not specified.")
            QMessageBox.warning(self, "Output Error", "Output PDF path required.")
            return
        # ...
        logger.info("Starting compression process for '%s'.", input_file)
        # ... (rest of start_compression) ...
        current_job_settings = self.get_current_gui_settings()
        try:
            doc = fitz.open(input_file)
            total_pages = len(doc)
            doc.close()
        except Exception as e:
            logger.error("Failed to open/read input PDF '%s': %s", input_file, e, exc_info=True)
            QMessageBox.critical(self, "PDF Error", f"Cannot open input PDF: {e}")
            return
        if total_pages == 0:
            logger.warning("Input PDF '%s' has no pages.", input_file)
            QMessageBox.warning(self, "PDF Error", "Input PDF has no pages.")
            return
        self.set_ui_processing_state(True)
        self.progress_bar.setValue(0)
        self.status_label.setText(f"Starting compression for {total_pages} pages...")
        self.compression_worker_obj = CompressionWorker(input_file, output_file, current_job_settings, total_pages)
        self.compression_thread = QThread()
        self.compression_worker_obj.moveToThread(self.compression_thread)
        self.compression_worker_obj.signals.progress_signal.connect(self.update_progress)
        self.compression_worker_obj.signals.status_update_signal.connect(self.update_status)
        self.compression_worker_obj.signals.result.connect(self.on_compression_finished)
        self.compression_worker_obj.signals.error.connect(self.on_compression_error)
        self.compression_worker_obj.signals.finished.connect(self.thread_cleanup)
        self.compression_thread.started.connect(self.compression_worker_obj.run)
        self.compression_thread.start()

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def update_status(self, message):
        self.status_label.setText(message)

    def on_compression_finished(self, output_filepath):
        logger.info("Compression finished successfully. Output file: '%s'", output_filepath)
        # ... (rest of on_compression_finished) ...
        self.set_ui_processing_state(False)
        self.progress_bar.setValue(100)
        final_message = "Compression successful (file details unavailable)."
        try:
            input_size_mb = os.path.getsize(self.input_path_edit.text()) / (1024 * 1024)
            output_size_mb = os.path.getsize(output_filepath) / (1024 * 1024)
            final_message = (
                f"Success! \nInput: {input_size_mb:.2f}MB, Output: {output_size_mb:.2f}MB. \nSaved to: {output_filepath}"
            )
            self.status_label.setText(final_message)

            # Create a message box with custom buttons
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Success")
            msg_box.setText(final_message + "\n\nWhat would you like to do?")
            msg_box.setIcon(QMessageBox.Question)

            # Add custom buttons
            open_file_btn = msg_box.addButton("Open PDF", QMessageBox.RejectRole)
            open_folder_btn = msg_box.addButton("Open Folder", QMessageBox.NoRole)
            cancel_btn = msg_box.addButton("Cancel", QMessageBox.YesRole)

            # Set default button
            msg_box.setDefaultButton(cancel_btn)

            # Show the message box
            msg_box.exec_()

            # Handle the response
            clicked_button = msg_box.clickedButton()

            if clicked_button == open_file_btn:
                try:
                    if os.name == "nt":
                        os.startfile(output_filepath)
                    elif os.name == "posix":
                        subprocess.Popen(["xdg-open", output_filepath])
                    else:
                        QMessageBox.information(self, "Open File", "Automatic opening not supported on this OS.")
                except Exception as e:
                    logger.error("Failed to open output file: %s", e)
                    QMessageBox.warning(self, "Open File Error", f"Could not open file:\n{e}")
            elif clicked_button == open_folder_btn:
                try:
                    directory = os.path.dirname(output_filepath)
                    if os.name == "nt":
                        os.startfile(directory)
                    elif os.name == "posix":
                        subprocess.Popen(["xdg-open", directory])
                    else:
                        QMessageBox.information(self, "Open Directory", "Automatic directory opening not supported on this OS.")
                except Exception as e:
                    logger.error("Failed to open directory: %s", e)
                    QMessageBox.warning(self, "Open Directory Error", f"Could not open directory:\n{e}")
            
            # Question about opening the repo website to give star
            if self.settings.get("ask_star_repo", False) is False:
                star_repo_btn = QMessageBox.question(
                    self,
                    "♥️ Support Development ♥️",
                    "Would you like to support development by giving a star on GitHub?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if star_repo_btn == QMessageBox.Yes:
                    webbrowser.open(REPO_URL)
                    QMessageBox.information(
                        self,
                        "♥️ THANK YOU ♥️",
                        "Thank you for your support! Your star helps us improve the project.",
                    )
                self.settings["ask_star_repo"] = True
                self.save_settings()
                
        except Exception as e:
            logger.error("Error getting file sizes after compression: %s", e)
            final_message = f"Compression finished. Error getting file sizes: {e}"
            self.status_label.setText(final_message)
            QMessageBox.information(self, "Failed", final_message)
        

    def on_compression_error(self, error_message):
        logger.error("Compression failed with error: %s", error_message)
        # ... (rest of on_compression_error) ...
        self.status_label.setText(f"Error: {error_message}")
        QMessageBox.critical(self, "Compression Error", error_message)
        self.progress_bar.setValue(0)
        # UI state re-enabled by thread_cleanup typically

    def cancel_compression(self):
        logger.info("Cancel compression button clicked.")
        # ... (rest of cancel_compression) ...
        if self.compression_worker_obj:
            self.status_label.setText("Cancellation requested...")
            self.compression_worker_obj.cancel()
            self.cancel_btn.setEnabled(False)

    def thread_cleanup(self):
        logger.debug("Main compression thread cleanup initiated.")
        # ... (rest of thread_cleanup) ...
        self.set_ui_processing_state(False)  # Ensure UI is re-enabled
        if self.compression_thread:
            if self.compression_thread.isRunning():
                logger.debug("Compression thread is running, attempting to quit.")
                self.compression_thread.quit()
                if not self.compression_thread.wait(500):
                    logger.warning("Compression thread did not quit gracefully, terminating.")
                    self.compression_thread.terminate()
                    self.compression_thread.wait()  # Wait for termination
            self.compression_thread.deleteLater()
            logger.debug("Compression QThread scheduled for deletion.")
        self.compression_thread = None
        self.compression_worker_obj = None
        logger.debug("Main compression thread resources cleaned up.")

    def trigger_preview_load_from_button(self):
        input_pdf = self.input_path_edit.text()
        logger.debug("Load/Refresh Preview button clicked for: '%s'", input_pdf)
        # ... (rest of trigger_preview_load_from_button) ...
        if self.preview_panel:
            if input_pdf and os.path.exists(input_pdf):
                self.preview_panel.load_pdf_document(input_pdf)
            else:
                self.preview_panel.load_pdf_document(None)
                if input_pdf:
                    logger.warning("Preview load failed: Input PDF '%s' not found.", input_pdf)
                    QMessageBox.warning(self, "Preview Error", f"Input PDF for preview not found:\n{input_pdf}")

    def set_ui_processing_state(self, is_processing):
        logger.debug("Setting UI processing state to: %s", is_processing)
        self.input_path_edit.setEnabled(not is_processing)
        self.browse_input_btn.setEnabled(not is_processing)
        self.output_path_edit.setEnabled(not is_processing)
        self.browse_output_btn.setEnabled(not is_processing)
        self.load_preview_btn.setEnabled(not is_processing)
        for group_box in self.findChildren(QGroupBox):
            group_box.setEnabled(not is_processing)
        self.compress_btn.setEnabled(not is_processing)
        self.reset_btn.setEnabled(not is_processing)
        self.cancel_btn.setEnabled(is_processing)

    def get_current_gui_settings(self):
        # No specific logging here, it's just data retrieval
        s = {}
        s["dpi"] = self.dpi_spinbox.value()
        s["quality"] = self.quality_slider.value()
        s["grayscale"] = self.grayscale_checkbox.isChecked()
        s["enhance_contrast"] = self.contrast_checkbox.isChecked()
        s["contrast_factor"] = self.contrast_slider.value() / 10.0
        s["enhance_brightness"] = self.brightness_checkbox.isChecked()
        s["brightness_factor"] = self.brightness_slider.value() / 10.0
        s["sharpen"] = self.sharpen_checkbox.isChecked()
        s["binarize"] = self.binarize_checkbox.isChecked()
        s["binarize_threshold"] = self.binarize_threshold_spinbox.value()
        s["denoise"] = self.denoise_checkbox.isChecked()
        return s

    def trigger_preview_load_from_input_edit(self):
        logger.debug("Input path edit finished, triggering preview load.")
        self.trigger_preview_load_from_button()
