import os
import fitz
import logging  # Import logging
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QToolBar,
    QAction,
    QLabel,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QSpinBox,
)
from PyQt5.QtCore import Qt, QTimer, QThreadPool, pyqtSlot, QPointF
from PyQt5.QtGui import QPixmap, QTransform, QPainter

from workers import PreviewPageWorker

logger = logging.getLogger(__name__)  # Logger for this module


class PreviewGraphicsView(QGraphicsView):
    # ... (No logging added here, but could be for specific events if needed) ...
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setRenderHint(QPainter.Antialiasing)
        self._zoom_factor = 1.0
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)

    def wheelEvent(self, event):
        # logger.debug("PreviewGraphicsView wheelEvent: delta %s", event.angleDelta().y())
        zoom_in_factor = 1.15
        zoom_out_factor = 1 / zoom_in_factor
        zoom_factor = zoom_in_factor if event.angleDelta().y() > 0 else zoom_out_factor
        new_zoom = self._zoom_factor * zoom_factor
        if 0.05 < new_zoom < 20.0:
            self.scale(zoom_factor, zoom_factor)
            self._zoom_factor = new_zoom

    def get_zoom_factor(self):
        return self._zoom_factor

    def reset_zoom_and_fit(self):
        # logger.debug("PreviewGraphicsView: Resetting zoom and fitting to view.")
        self.setTransform(QTransform())
        self._zoom_factor = 1.0
        self.fit_in_view_if_possible()

    def fit_in_view_if_possible(self):
        if not self.scene() or not self.scene().items():
            return
        items = self.scene().items()
        if items and isinstance(items[0], QGraphicsPixmapItem) and not items[0].pixmap().isNull():
            self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)
            self._zoom_factor = self.transform().m11()


class PreviewPanel(QWidget):
    def __init__(self, main_window_ref, parent=None):
        super().__init__(parent)
        # ... (rest of __init__ is the same, add logger init) ...
        self.main_window_ref = main_window_ref
        self.current_pdf_path = None
        self.current_page_num = 0
        self.total_pages = 0
        self.original_page_pixmap = QPixmap()
        self.processed_page_pixmap = QPixmap()
        self.showing_original = True
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(1)
        self.preview_update_timer = QTimer(self)
        self.preview_update_timer.setSingleShot(True)
        self.preview_update_timer.timeout.connect(self._trigger_processed_render_job_from_timer)
        self.render_job_id_counter = 0
        self.active_original_render_id = -1
        self.active_processed_render_id = -1
        self.page_dimensions_cache = {}
        logger.debug("PreviewPanel initialized.")
        self.init_ui()

    # ... (init_ui, set_controls_enabled remain the same) ...
    def init_ui(self):
        # ...
        logger.debug("PreviewPanel UI initializing.")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        toolbar = QToolBar("Preview Controls")
        layout.addWidget(toolbar)
        self.prev_action = QAction("Previous", self)
        self.prev_action.triggered.connect(self.prev_page)
        toolbar.addAction(self.prev_action)
        self.page_label = QLabel("Page: 0 / 0")
        toolbar.addWidget(self.page_label)
        self.next_action = QAction("Next", self)
        self.next_action.triggered.connect(self.next_page)
        toolbar.addAction(self.next_action)
        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Go to:"))
        self.page_spinbox = QSpinBox(self)
        self.page_spinbox.setMinimum(1)
        self.page_spinbox.valueChanged.connect(self.go_to_page_from_spinbox)
        self.page_spinbox.setKeyboardTracking(False)
        toolbar.addWidget(self.page_spinbox)
        toolbar.addSeparator()
        self.compare_action = QAction("Show Processed", self)
        self.compare_action.setCheckable(True)
        self.compare_action.setChecked(False)
        self.compare_action.triggered.connect(self.toggle_compare_view)
        toolbar.addAction(self.compare_action)
        self.fit_view_action = QAction("Fit/Reset Zoom", self)
        self.fit_view_action.triggered.connect(lambda: self.view.reset_zoom_and_fit())
        toolbar.addAction(self.fit_view_action)
        self.scene = QGraphicsScene(self)
        self.view = PreviewGraphicsView(self.scene, self)
        self.pixmap_item = QGraphicsPixmapItem()
        self.scene.addItem(self.pixmap_item)
        layout.addWidget(self.view)
        self.set_controls_enabled(False)
        logger.debug("PreviewPanel UI initialized.")
        # Set the background color of the QGraphicsView to light gray
        self.view.setBackgroundBrush(Qt.lightGray)
        
        # Set the scroll bars itself to darker gray
        self.view.setStyleSheet("""
            QGraphicsView {
                background-color: lightgray;
            }
            QScrollBar::handle:vertical {
                background-color: darkgray;
            }
            QScrollBar::handle:horizontal {
                background-color: darkgray;
            }
        """)
        
        # Add spacing between toolbar elements
        toolbar.setStyleSheet("""
            QToolBar > * {
                margin-right: 8px;
            }
            QToolBar QLabel, QToolBar QSpinBox {
                margin-right: 4px;
            }
            QToolButton {
                border: 1px solid #888;
                border-radius: 4px;
                padding: 2px 8px;
                background: #f5f5f5;
            }
            QToolButton:checked {
                background: #e0e0e0;
                border: 2px solid #555;
            }
            QToolButton:hover {
                background: #e0e0e0;
            }
            QToolButton:pressed {
                background: #d0d0d0;
                border: 2px solid #555;
            }
        """)
        
        

    def set_controls_enabled(self, enabled):
        is_valid = enabled and self.total_pages > 0
        self.prev_action.setEnabled(is_valid and self.current_page_num > 0)
        self.next_action.setEnabled(is_valid and self.current_page_num < self.total_pages - 1)
        self.compare_action.setEnabled(is_valid)
        self.page_spinbox.setEnabled(is_valid)
        self.fit_view_action.setEnabled(is_valid)
        if is_valid:
            self.page_spinbox.setMaximum(self.total_pages)
        else:
            self.page_spinbox.setMaximum(1)
            self.page_spinbox.setMinimum(1)
        logger.debug("PreviewPanel controls enabled: %s (Total pages: %d)", is_valid, self.total_pages)

    def load_pdf_document(self, pdf_path):
        logger.info("PreviewPanel: Loading PDF document: '%s'", pdf_path)
        self.page_dimensions_cache.clear()
        if not pdf_path or not os.path.exists(pdf_path):
            logger.warning("PreviewPanel: PDF path is invalid or file does not exist: '%s'", pdf_path)
            self._clear_preview_state(
                message=f"Preview: PDF not found at '{pdf_path}'" if pdf_path else "Preview: No PDF loaded."
            )
            return False
        try:
            temp_doc = fitz.open(pdf_path)
            self.total_pages = len(temp_doc)
            temp_doc.close()
            self.current_pdf_path = pdf_path
            logger.info("PreviewPanel: Loaded '%s', %d pages.", pdf_path, self.total_pages)

            if self.total_pages > 0:
                self.current_page_num = 0
                self.set_controls_enabled(True)
                self.showing_original = True
                self.compare_action.setChecked(False)
                self.compare_action.setText("Show Processed")
                self._load_and_display_current_page()
                return True
            else:
                logger.warning("PreviewPanel: PDF '%s' has no pages.", pdf_path)
                self._clear_preview_state(message=f"Preview: PDF '{os.path.basename(pdf_path)}' has no pages.")
                return False
        except Exception as e:
            logger.error("PreviewPanel: Error loading PDF '%s': %s", pdf_path, e, exc_info=True)
            self._clear_preview_state(message=f"Preview: Error loading PDF '{os.path.basename(pdf_path)}'.")
            return False

    def _clear_preview_state(self, message="Preview cleared."):
        logger.debug("PreviewPanel: Clearing preview state. Message: %s", message)
        # ... (rest of _clear_preview_state remains the same) ...
        self.current_pdf_path = None
        self.total_pages = 0
        self.current_page_num = 0
        if self.pixmap_item:
            self.pixmap_item.setPixmap(QPixmap())
        self.original_page_pixmap = QPixmap()
        self.processed_page_pixmap = QPixmap()
        self.update_page_label()
        self.set_controls_enabled(False)
        self.main_window_ref.status_label.setText(message)
        self.active_original_render_id = -1
        self.active_processed_render_id = -1

    def _load_and_display_current_page(self):
        logger.debug(
            "PreviewPanel: Loading and displaying page %d of '%s'.", self.current_page_num + 1, self.current_pdf_path
        )
        # ... (rest of _load_and_display_current_page remains the same) ...
        if not self.current_pdf_path or not (0 <= self.current_page_num < self.total_pages):
            logger.warning(
                "PreviewPanel: Cannot load page, invalid state. PDF: '%s', Page: %d, Total: %d",
                self.current_pdf_path,
                self.current_page_num,
                self.total_pages,
            )
            return
        self.original_page_pixmap = QPixmap()
        self.processed_page_pixmap = QPixmap()
        if self.showing_original:
            self.set_pixmap_on_scene(self.original_page_pixmap)
        else:
            self.set_pixmap_on_scene(self.processed_page_pixmap)
        self._trigger_render_job(is_original=True)
        self._trigger_render_job(is_original=False)
        self.update_page_label()
        self.page_spinbox.blockSignals(True)
        self.page_spinbox.setValue(self.current_page_num + 1)
        self.page_spinbox.blockSignals(False)
        self.set_controls_enabled(True)  # Re-evaluate nav button states

    def _trigger_render_job(self, is_original):
        if not self.current_pdf_path:
            logger.warning("PreviewPanel: Cannot trigger render job, no PDF path.")
            return

        self.render_job_id_counter += 1
        current_job_id = self.render_job_id_counter
        render_type = "Original" if is_original else "Processed"

        if is_original:
            self.active_original_render_id = current_job_id
            logger.debug(
                "PreviewPanel: Triggering %s render for page %d. New Active ID: %d",
                render_type,
                self.current_page_num + 1,
                self.active_original_render_id,
            )
        else:
            self.active_processed_render_id = current_job_id
            logger.debug(
                "PreviewPanel: Triggering %s render for page %d. New Active ID: %d",
                render_type,
                self.current_page_num + 1,
                self.active_processed_render_id,
            )
            if not self.showing_original:
                self.main_window_ref.status_label.setText(
                    f"Preview: Rendering {render_type.lower()} page {self.current_page_num + 1} (ID: {current_job_id})..."
                )

        settings = self.main_window_ref.get_current_gui_settings()
        worker = PreviewPageWorker(self.current_pdf_path, self.current_page_num, settings, is_original, current_job_id)
        worker.signals.preview_result_signal.connect(self._on_preview_page_rendered)
        worker.signals.error.connect(
            lambda err_msg: [
                logger.warning("PreviewPanel: Worker error signal: %s", err_msg),
                self.main_window_ref.status_label.setText(f"Preview Error: {err_msg}"),
            ]
        )
        self.thread_pool.start(worker)

    @pyqtSlot(QPixmap, bool, int)
    def _on_preview_page_rendered(self, qpix, is_original_flag, received_request_id):
        logger.debug(
            "PreviewPanel: Render job completed. Received Req ID: %d, Original Flag: %s. Active Orig ID: %d, Active Proc ID: %d",
            received_request_id,
            is_original_flag,
            self.active_original_render_id,
            self.active_processed_render_id,
        )
        valid_render = False
        render_type = "Original" if is_original_flag else "Processed"

        if is_original_flag and received_request_id == self.active_original_render_id:
            self.original_page_pixmap = qpix
            if self.showing_original:
                self.set_pixmap_on_scene(self.original_page_pixmap)
            valid_render = True
            logger.debug(
                "PreviewPanel: Updated original pixmap cache for page %d (Req ID %d).",
                self.current_page_num + 1,
                received_request_id,
            )
        elif not is_original_flag and received_request_id == self.active_processed_render_id:
            self.processed_page_pixmap = qpix
            if not self.showing_original:
                self.set_pixmap_on_scene(self.processed_page_pixmap)
            valid_render = True
            logger.debug(
                "PreviewPanel: Updated processed pixmap cache for page %d (Req ID %d).",
                self.current_page_num + 1,
                received_request_id,
            )

        if valid_render and not qpix.isNull():
            status_message = (
                f"Preview: {render_type} page {self.current_page_num + 1} updated (ID: {received_request_id})."
            )
            if self.is_current_view_active(
                is_original_flag
            ):  # Only update status if this view is active or just became active
                self.main_window_ref.status_label.setText(status_message)
        elif not valid_render:
            logger.info(
                "PreviewPanel: Discarded stale render (Req ID %d) for page %d, type: %s.",
                received_request_id,
                self.current_page_num + 1,
                render_type,
            )
        elif qpix.isNull():
            logger.warning(
                "PreviewPanel: Received null QPixmap for %s page %d (Req ID %d). Render likely failed.",
                render_type,
                self.current_page_num + 1,
                received_request_id,
            )

    def is_current_view_active(self, is_original_flag):
        """Checks if the rendered pixmap type (original/processed) is the one currently meant to be shown."""
        return (is_original_flag and self.showing_original) or (not is_original_flag and not self.showing_original)

    # ... (set_pixmap_on_scene remains the same) ...
    def set_pixmap_on_scene(self, qpix):
        if qpix.isNull() and self.pixmap_item.pixmap().isNull():
            return
        current_zoom = self.view.get_zoom_factor()
        is_default_zoom_or_identity = abs(current_zoom - 1.0) < 0.01 or self.view.transform().isIdentity()
        self.pixmap_item.setPixmap(qpix)
        if not qpix.isNull():
            self.scene.setSceneRect(self.pixmap_item.boundingRect())
            if is_default_zoom_or_identity:
                self.view.fit_in_view_if_possible()
        else:
            self.scene.setSceneRect(0, 0, 1, 1)

    def update_page_label(self):
        # ... (remains the same) ...
        self.page_label.setText(
            f"Page: {self.current_page_num + 1 if self.total_pages > 0 else 0} / {self.total_pages}"
        )

    def prev_page(self):
        if self.total_pages > 0 and self.current_page_num > 0:
            self.current_page_num -= 1
            logger.debug("PreviewPanel: Navigating to previous page: %d", self.current_page_num + 1)
            self._load_and_display_current_page()

    def next_page(self):
        if self.total_pages > 0 and self.current_page_num < self.total_pages - 1:
            self.current_page_num += 1
            logger.debug("PreviewPanel: Navigating to next page: %d", self.current_page_num + 1)
            self._load_and_display_current_page()

    def go_to_page_from_spinbox(self, page_value_one_indexed):
        if self.total_pages > 0 and (1 <= page_value_one_indexed <= self.total_pages):
            new_page_zero_indexed = page_value_one_indexed - 1
            if new_page_zero_indexed != self.current_page_num:
                self.current_page_num = new_page_zero_indexed
                logger.debug("PreviewPanel: Navigating to page %d from spinbox.", self.current_page_num + 1)
                self._load_and_display_current_page()

    def toggle_compare_view(self):
        should_show_processed = self.compare_action.isChecked()
        self.showing_original = not should_show_processed
        logger.debug(
            "PreviewPanel: Toggling compare view. Show original: %s. Action checked (show processed): %s",
            self.showing_original,
            should_show_processed,
        )

        if should_show_processed:  # Now should show Processed
            self.main_window_ref.status_label.setText("Preview: Showing Processed Page")
            self.compare_action.setText("Show Original")
            if self.processed_page_pixmap.isNull():
                logger.debug("PreviewPanel: Processed pixmap is null, triggering re-render.")
                self._trigger_render_job(is_original=False)
            self.set_pixmap_on_scene(self.processed_page_pixmap)
        else:  # Should show Original
            self.main_window_ref.status_label.setText("Preview: Showing Original Page")
            self.compare_action.setText("Show Processed")
            if self.original_page_pixmap.isNull():
                logger.debug("PreviewPanel: Original pixmap is null, triggering re-render.")
                self._trigger_render_job(is_original=True)
            self.set_pixmap_on_scene(self.original_page_pixmap)

    def schedule_processed_preview_update(self):
        if self.current_pdf_path and self.total_pages > 0:
            logger.debug("PreviewPanel: Scheduling processed preview update for page %d.", self.current_page_num + 1)
            self.preview_update_timer.start(250)

    def _trigger_processed_render_job_from_timer(self):
        logger.debug("PreviewPanel: Timer fired, triggering processed render for page %d.", self.current_page_num + 1)
        if self.current_pdf_path and self.total_pages > 0:
            self._trigger_render_job(is_original=False)

    def close_current_document(self):
        logger.debug("PreviewPanel: close_current_document called. Waiting for thread pool to finish.")
        self.thread_pool.waitForDone(1000)
        logger.debug("PreviewPanel: Thread pool finished or timed out.")
