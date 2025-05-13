import io
import os
import fitz  # PyMuPDF
from PIL import Image, ImageEnhance, ImageFilter
import concurrent.futures
import logging

from PyQt5.QtCore import QObject, QRunnable, pyqtSlot
from PyQt5.QtGui import QPixmap
from utils import WorkerSignals, fitz_pixmap_to_qpixmap  # Assuming utils.py is in the same directory
from pdf_processor import compress_page

logger = logging.getLogger(__name__)


class CompressionWorker(QObject):
    signals = WorkerSignals()

    def __init__(self, input_path, output_path, settings, total_pages):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.settings = settings
        self.total_pages = total_pages
        self.is_cancelled = False
        logger.debug(
            "CompressionWorker initialized for '%s', %d pages. Output: '%s'. Settings: %s",
            self.input_path,
            self.total_pages,
            self.output_path,
            self.settings,
        )

    def cancel(self):
        self.is_cancelled = True
        logger.info("CompressionWorker cancellation requested for '%s'", self.input_path)

    @pyqtSlot()
    def run(self):
        logger.info("CompressionWorker started for '%s' (%d pages).", self.input_path, self.total_pages)
        try:
            results = {}
            processed_page_count = 0
            max_workers = os.cpu_count()
            self.signals.status_update_signal.emit(
                f"Processing {self.total_pages} pages using up to {max_workers} workers..."
            )
            logger.debug("Using %d workers for parallel processing of '%s'.", max_workers, self.input_path)

            with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(compress_page, i, self.input_path, self.settings): i
                    for i in range(self.total_pages)
                }

                for future in concurrent.futures.as_completed(futures):
                    if self.is_cancelled:
                        logger.info("Cancellation confirmed during page processing loop for '%s'.", self.input_path)
                        # Attempt to cancel remaining futures (may not work for already running tasks)
                        for f_key in futures:
                            if not f_key.done():  # Only cancel if not done
                                f_key.cancel()
                        self.signals.error.emit("Compression cancelled by user.")
                        return

                    page_num_completed = futures[future]
                    try:
                        p_num, img_bytes, fmt, orig_w, orig_h = (
                            future.result()
                        )  # This can raise exceptions from compress_page
                        if img_bytes:
                            results[p_num] = (img_bytes, fmt, orig_w, orig_h)
                            logger.debug("Page %d from '%s' processed successfully by worker.", p_num, self.input_path)
                        else:
                            # This case implies compress_page returned None for img_bytes, indicating an error logged there
                            logger.warning(
                                "Page %d from '%s' failed processing (returned no image bytes).",
                                page_num_completed,
                                self.input_path,
                            )
                            self.signals.status_update_signal.emit(
                                f"Warning: Page {page_num_completed} failed processing."
                            )
                    except concurrent.futures.CancelledError:
                        logger.info(
                            "A page processing task was cancelled for '%s', page %d.",
                            self.input_path,
                            page_num_completed,
                        )
                    except Exception as exc:
                        logger.error(
                            "Page %d from '%s' generated an exception during future.result(): %s",
                            page_num_completed,
                            self.input_path,
                            exc,
                            exc_info=False,
                        )  # Keep exc_info=False for brevity unless needed
                        self.signals.status_update_signal.emit(
                            f"Page {page_num_completed} generated an exception: {exc}"
                        )

                    processed_page_count += 1
                    if self.total_pages > 0:  # Avoid division by zero if PDF was empty but somehow reached here
                        progress_percent = int((processed_page_count / self.total_pages) * 100)
                        self.signals.progress_signal.emit(progress_percent)
                    self.signals.page_done_signal.emit(processed_page_count)

            if self.is_cancelled:
                logger.info("Compression cancelled before final assembly for '%s'.", self.input_path)
                return

            if not results:
                logger.error("No pages were successfully processed for '%s'.", self.input_path)
                self.signals.error.emit("Error: No pages were successfully processed.")
                return

            self.signals.status_update_signal.emit("Sorting processed pages...")
            logger.debug("Sorting %d processed pages for '%s'.", len(results), self.input_path)
            sorted_results_data = [results[i] for i in sorted(results.keys())]

            self.signals.status_update_signal.emit("Assembling compressed PDF...")
            logger.info("Assembling final PDF with %d pages for '%s'.", len(sorted_results_data), self.input_path)
            output_doc = fitz.open()
            for i, (img_bytes, fmt, orig_w, orig_h) in enumerate(sorted_results_data):
                if self.is_cancelled:
                    logger.info("Cancellation confirmed during PDF assembly for '%s'.", self.input_path)
                    output_doc.close()
                    self.signals.error.emit("Cancellation during PDF assembly.")
                    return
                try:
                    page = output_doc.new_page(width=orig_w, height=orig_h)
                    page.insert_image(page.rect, stream=img_bytes)
                except Exception as e_insert:
                    logger.error(
                        "Error inserting image for page index %d (original page %s) into output PDF for '%s': %s",
                        i,
                        sorted(results.keys())[i],
                        self.input_path,
                        e_insert,
                        exc_info=False,
                    )
                    self.signals.status_update_signal.emit(f"Error inserting image for page {i}: {e_insert}")
                    output_doc.new_page(width=orig_w or 595, height=orig_h or 842)

            if self.is_cancelled:
                return

            self.signals.status_update_signal.emit(f"Saving compressed PDF to: {self.output_path}")
            logger.info("Saving final PDF to '%s' for input '%s'.", self.output_path, self.input_path)
            output_doc.save(self.output_path, garbage=4, deflate=True)
            output_doc.close()
            logger.info("Compression successful for '%s'. Output: '%s'", self.input_path, self.output_path)
            self.signals.result.emit(self.output_path)  # Emit output path on success
            self.signals.finished.emit()

        except Exception as e:
            logger.critical("Unhandled error in CompressionWorker.run for '%s': %s", self.input_path, e, exc_info=True)
            self.signals.error.emit(f"An critical error occurred during compression: {str(e)}")
        finally:
            logger.debug("CompressionWorker.run finished for '%s'.", self.input_path)


class PreviewPageWorker(QRunnable):
    def __init__(self, pdf_path, page_num, settings, is_original_render, request_id):
        super().__init__()
        self.pdf_path = pdf_path
        self.page_num = page_num
        self.settings = settings
        self.is_original_render = is_original_render
        self.request_id = request_id
        self.signals = WorkerSignals()
        logger.debug(
            "PreviewPageWorker (Req ID %d) initialized for '%s', page %d, original: %s. Settings: %s",
            self.request_id,
            self.pdf_path,
            self.page_num,
            self.is_original_render,
            self.settings,
        )

    @pyqtSlot()
    def run(self):
        logger.debug(
            "PreviewPageWorker (Req ID %d) starting for page %d ('%s'), original: %s.",
            self.request_id,
            self.page_num,
            self.pdf_path,
            self.is_original_render,
        )
        try:
            fitz_pix = self._render_page_to_fitz_pixmap()  # This method is what we're fixing
            if fitz_pix:
                qpix = fitz_pixmap_to_qpixmap(fitz_pix)
                if qpix.isNull() and fitz_pix.width > 0 and fitz_pix.height > 0:
                    logger.warning(
                        "PreviewPageWorker (Req ID %d): fitz_pixmap_to_qpixmap returned null QPixmap for page %d, though fitz_pix seemed valid (w:%d,h:%d).",
                        self.request_id,
                        self.page_num,
                        fitz_pix.width,
                        fitz_pix.height,
                    )
                self.signals.preview_result_signal.emit(qpix, self.is_original_render, self.request_id)
                logger.debug(
                    "PreviewPageWorker (Req ID %d) emitted result for page %d.", self.request_id, self.page_num
                )
            else:  # _render_page_to_fitz_pixmap returned None
                logger.warning(
                    "PreviewPageWorker (Req ID %d): _render_page_to_fitz_pixmap returned None for page %d. No QPixmap to emit.",
                    self.request_id,
                    self.page_num,
                )
                # Emit a null QPixmap to signal completion but with failure to render.
                # This allows the UI to potentially clear the preview or show an error image.
                # self.signals.preview_result_signal.emit(QPixmap(), self.is_original_render, self.request_id)
                # Or, if error signal is preferred for this case:
                self.signals.error.emit(
                    f"Preview (Req ID {self.request_id}): Failed to render page {self.page_num + 1} (pixmap was None)."
                )

        except Exception as e:
            logger.error(
                "PreviewPageWorker (Req ID %d) unhandled error during run for page %d ('%s'): %s",
                self.request_id,
                self.page_num,
                self.pdf_path,
                e,
                exc_info=True,
            )
            self.signals.error.emit(
                f"Preview (Req ID {self.request_id}) critical render error for page {self.page_num + 1}: {str(e)}"
            )
        finally:
            self.signals.finished.emit()
            logger.debug(
                "PreviewPageWorker (Req ID %d) finished for page %d ('%s').",
                self.request_id,
                self.page_num,
                self.pdf_path,
            )

    def _render_page_to_fitz_pixmap(self):
        doc = None
        try:
            doc = fitz.open(self.pdf_path)
            if not (0 <= self.page_num < len(doc)):
                logger.warning(
                    "PreviewPageWorker (Req ID %d): Invalid page number %d for PDF '%s' (total %d pages).",
                    self.request_id,
                    self.page_num,
                    self.pdf_path,
                    len(doc) if doc else 0,
                )
                if doc:
                    doc.close()
                return None

            page = doc.load_page(self.page_num)
            target_dpi = self.settings.get("dpi", 150)

            if self.is_original_render:
                preview_dpi_original = self.settings.get("preview_original_dpi", 150)
                zoom = preview_dpi_original / 72.0
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                logger.debug(
                    "PreviewPageWorker (Req ID %d): Rendered original page %d at %d DPI.",
                    self.request_id,
                    self.page_num,
                    preview_dpi_original,
                )
            else:  # Processed view
                zoom = target_dpi / 72.0
                mat = fitz.Matrix(zoom, zoom)
                temp_pix = page.get_pixmap(matrix=mat, alpha=False)

                pil_img = Image.frombytes("RGB", [temp_pix.width, temp_pix.height], temp_pix.samples)

                # Apply enhancements
                if self.settings.get("denoise", False):
                    pil_img = pil_img.filter(ImageFilter.MedianFilter(size=3))
                if self.settings.get("enhance_contrast", False):
                    enhancer = ImageEnhance.Contrast(pil_img)
                    pil_img = enhancer.enhance(self.settings.get("contrast_factor", 1.0))
                if self.settings.get("enhance_brightness", False):
                    enhancer = ImageEnhance.Brightness(pil_img)
                    pil_img = enhancer.enhance(self.settings.get("brightness_factor", 1.0))
                if self.settings.get("sharpen", False):
                    pil_img = pil_img.filter(ImageFilter.SHARPEN)

                if self.settings.get("binarize", False):
                    pil_img = pil_img.convert("L")
                    threshold = self.settings.get("binarize_threshold", 128)
                    pil_img = pil_img.point(lambda x: 0 if x < threshold else 255, "1")
                elif self.settings.get("grayscale", False):
                    pil_img = pil_img.convert("L")

                logger.debug(
                    "PreviewPageWorker (Req ID %d): Applied PIL enhancements for processed page %d. PIL mode: '%s', Size: %dx%d",
                    self.request_id,
                    self.page_num,
                    pil_img.mode,
                    pil_img.width,
                    pil_img.height,
                )

                # --- START: Simulate JPEG compression for preview ---
                output_format_for_preview = self.settings.get("output_format", "JPEG")
                if output_format_for_preview == "JPEG":
                    jpeg_quality = self.settings.get("quality", 80)
                    logger.debug(
                        "PreviewPageWorker (Req ID %d): Simulating JPEG compression with quality %d for page %d.",
                        self.request_id,
                        jpeg_quality,
                        self.page_num,
                    )

                    # Ensure pil_img is in a mode that can be saved as JPEG (RGB or L)
                    if pil_img.mode not in ("L", "RGB"):
                        logger.warning(
                            "PreviewPageWorker (Req ID %d): PIL mode '%s' is not L or RGB before JPEG simulation. Converting to RGB.",
                            self.request_id,
                            pil_img.mode,
                        )
                        pil_img = pil_img.convert("RGB")

                    img_byte_arr = io.BytesIO()
                    try:
                        pil_img.save(img_byte_arr, format="JPEG", quality=jpeg_quality)
                        img_byte_arr.seek(0)  # Rewind buffer
                        pil_img = Image.open(img_byte_arr)  # Reload image with JPEG artifacts
                        logger.debug(
                            "PreviewPageWorker (Req ID %d): Reloaded image after JPEG simulation. New mode: '%s', Size: %dx%d",
                            self.request_id,
                            pil_img.mode,
                            pil_img.width,
                            pil_img.height,
                        )
                    except Exception as e_jpeg_sim:
                        logger.error(
                            "PreviewPageWorker (Req ID %d): Error during JPEG simulation for page %d: %s",
                            self.request_id,
                            self.page_num,
                            e_jpeg_sim,
                            exc_info=True,
                        )
                        # If JPEG simulation fails, we might proceed with the non-simulated pil_img
                        # or return None to indicate a preview generation issue.
                        # For now, proceed with pil_img as it was before attempting simulation.
                # --- END: Simulate JPEG compression for preview ---

                # Defensive check for PIL image dimensions
                if pil_img.width == 0 or pil_img.height == 0:
                    logger.error(
                        "PreviewPageWorker (Req ID %d): PIL image has zero width or height after enhancements (w:%d, h:%d). Cannot create fitz.Pixmap.",
                        self.request_id,
                        pil_img.width,
                        pil_img.height,
                    )
                    if doc:
                        doc.close()
                        return None

                pil_img_for_fitz = pil_img  # Use this for clarity

                # --- Convert PIL Image back to fitz.Pixmap ---
                try:
                    # Attempt 1: Direct conversion using fitz.Pixmap(pil_image_object)
                    pix = fitz.Pixmap(pil_img_for_fitz)
                    logger.debug(
                        "PreviewPageWorker (Req ID %d): Successfully created fitz.Pixmap directly from PIL image (mode '%s').",
                        self.request_id,
                        pil_img_for_fitz.mode,
                    )
                except Exception as e_direct_conversion:
                    logger.warning(
                        "PreviewPageWorker (Req ID %d): fitz.Pixmap(pil_img) direct conversion failed (PIL mode '%s'): %s. Trying explicit W,H,S constructor.",
                        self.request_id,
                        pil_img_for_fitz.mode,
                        e_direct_conversion,
                    )
                    try:
                        width = pil_img_for_fitz.width
                        height = pil_img_for_fitz.height
                        samples = pil_img_for_fitz.tobytes()

                        if not samples:
                            logger.error(
                                "PreviewPageWorker (Req ID %d): Fallback failed - PIL image tobytes() returned empty samples (mode '%s').",
                                self.request_id,
                                pil_img_for_fitz.mode,
                            )
                            if doc:
                                doc.close()
                                return None

                        current_pil_mode = pil_img_for_fitz.mode
                        cs = None
                        if current_pil_mode == "1" or current_pil_mode == "L":
                            # cs = fitz.csGRAY
                            logger.debug(
                                "PreviewPageWorker (Req ID %d): PIL mode '%s' detected. We will convert it to RGB.",
                                self.request_id,
                                current_pil_mode,
                            )
                            temp_rgb_pil = pil_img_for_fitz.convert("RGB")
                            width = temp_rgb_pil.width
                            height = temp_rgb_pil.height
                            samples = temp_rgb_pil.tobytes()
                            cs = fitz.csRGB
                        elif current_pil_mode == "RGB":
                            cs = fitz.csRGB
                        else:  # Fallback for unexpected modes, convert to RGB
                            logger.warning(
                                "PreviewPageWorker (Req ID %d): Unexpected PIL mode '%s' in fallback. Converting to RGB.",
                                self.request_id,
                                current_pil_mode,
                            )
                            temp_rgb_pil = pil_img_for_fitz.convert("RGB")
                            width = temp_rgb_pil.width
                            height = temp_rgb_pil.height
                            samples = temp_rgb_pil.tobytes()
                            cs = fitz.csRGB

                        if cs is None:  # Should not happen with the logic above
                            logger.error(
                                "PreviewPageWorker (Req ID %d): Critical - Could not determine colorspace for explicit construction.",
                                self.request_id,
                            )
                            if doc:
                                doc.close()
                                return None

                        # *** THE FIX IS HERE: Use explicit W, H, S constructor ***
                        pix = fitz.Pixmap(cs, width, height, samples, 0)  # alpha = 0
                        logger.debug(
                            "PreviewPageWorker (Req ID %d): Successfully created fitz.Pixmap using explicit W,H,S constructor (PIL mode '%s' -> cs '%s').",
                            self.request_id,
                            current_pil_mode,
                            cs.name if cs else "None",
                        )
                    except Exception as e_explicit_construction:
                        logger.error(
                            "PreviewPageWorker (Req ID %d): Explicit construction of fitz.Pixmap from samples also failed (PIL mode '%s'): %s",
                            self.request_id,
                            pil_img_for_fitz.mode,
                            e_explicit_construction,
                            exc_info=True,
                        )
                        if doc:
                            doc.close()
                            return None

            if doc:
                doc.close()
            return pix
        except Exception as e:
            logger.error(
                "PreviewPageWorker (Req ID %d): Error in _render_page_to_fitz_pixmap for page %d ('%s'): %s",
                self.request_id,
                self.page_num,
                self.pdf_path,
                e,
                exc_info=True,
            )
            if doc:
                doc.close()
            return None  # Explicitly return None on any exception
