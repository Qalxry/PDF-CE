import os
import logging
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap

logger = logging.getLogger(__name__)

CONFIG_FILE = "pdf_compressor_settings.json"
DEFAULT_SETTINGS = {
    "input_path": "",
    "output_path": "",
    "dpi": 150,
    "quality": 80,
    "grayscale": False,
    "enhance_contrast": False,
    "contrast_factor": 1.0,
    "enhance_brightness": False,
    "brightness_factor": 1.0,
    "sharpen": False,
    "binarize": False,
    "binarize_threshold": 128,
    "denoise": False,
    "ocr_placeholder": False,
    "ask_star_repo": False,
}


class WorkerSignals(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(str)
    result = pyqtSignal(object)
    progress_signal = pyqtSignal(int)
    page_done_signal = pyqtSignal(int)
    status_update_signal = pyqtSignal(str)
    preview_result_signal = pyqtSignal(QPixmap, bool, int)


def fitz_pixmap_to_qpixmap(fitz_pix):
    """Converts a fitz.Pixmap to a QPixmap."""
    if not fitz_pix or fitz_pix.width == 0 or fitz_pix.height == 0:  # Handle null or empty pixmap
        logger.warning("fitz_pixmap_to_qpixmap: Received null or empty fitz.Pixmap.")
        return QPixmap()
    try:
        if fitz_pix.alpha:
            # For RGBA data from fitz.Pixmap.samples (R,G,B,A byte order)
            image_format = QImage.Format_RGBA8888
            # If samples are premultiplied alpha, use Format_RGBA8888_Premultiplied
        else:
            # For RGB data from fitz.Pixmap.samples (R,G,B byte order)
            image_format = QImage.Format_RGB888  # Corrected from RGB8888

        if not isinstance(fitz_pix.samples, (bytes, bytearray)):
            logger.error(
                "fitz_pix.samples is not bytes or bytearray (type: %s, len: %s). Cannot create QImage.",
                type(fitz_pix.samples),
                len(fitz_pix.samples) if hasattr(fitz_pix.samples, "__len__") else "N/A",
            )
            return QPixmap()

        # Basic check for sample size consistency
        expected_bytes = (
            fitz_pix.width * fitz_pix.height * fitz_pix.n
        )  # n is number of components (e.g., 3 for RGB, 4 for RGBA)
        if len(fitz_pix.samples) < expected_bytes:  # Stride might be larger, but samples shouldn't be smaller
            logger.error(
                "fitz_pix.samples length (%d) is less than expected (%d based on w:%d, h:%d, n:%d). QImage might fail or be incorrect.",
                len(fitz_pix.samples),
                expected_bytes,
                fitz_pix.width,
                fitz_pix.height,
                fitz_pix.n,
            )
            # Proceed with caution or return QPixmap() if this is a hard error.

        qimage = QImage(fitz_pix.samples, fitz_pix.width, fitz_pix.height, fitz_pix.stride, image_format)

        if qimage.isNull():
            logger.error(
                "QImage creation resulted in a null QImage. fitz.Pixmap details: w:%d, h:%d, stride:%d, alpha:%s, n:%d, format:%s",
                fitz_pix.width,
                fitz_pix.height,
                fitz_pix.stride,
                fitz_pix.alpha,
                fitz_pix.n,
                image_format,
            )
            return QPixmap()

        return QPixmap.fromImage(qimage)
    except Exception as e:
        logger.error(
            "Error converting fitz.Pixmap (w:%s,h:%s,s:%s,a:%s,n:%s) to QPixmap: %s",
            fitz_pix.width,
            fitz_pix.height,
            fitz_pix.stride,
            fitz_pix.alpha,
            fitz_pix.n,
            e,
            exc_info=False,
        )  # Set exc_info=True for full traceback if needed
        return QPixmap()
