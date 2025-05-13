import fitz
from PIL import Image, ImageEnhance, ImageFilter
import io
import logging

logger = logging.getLogger(__name__)


def compress_page(page_num, input_pdf_path, settings):
    logger.debug(
        "Compressing page %d from '%s'. DPI: %d, Quality: %d, Grayscale: %s, Binarize: %s",
        page_num,
        input_pdf_path,
        settings.get("dpi"),
        settings.get("quality"),
        settings.get("grayscale"),
        settings.get("binarize"),
    )
    doc_to_close = None
    try:
        doc_to_close = fitz.open(input_pdf_path)
        page = doc_to_close.load_page(page_num)

        original_rect = page.rect
        original_width = original_rect.width
        original_height = original_rect.height

        zoom = settings["dpi"] / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # ... (enhancement logic) ...
        if settings.get("denoise", False):
            img = img.filter(ImageFilter.MedianFilter(size=3))
            logger.debug("Page %d: Applied denoise.", page_num)
        if settings.get("enhance_contrast", False):
            factor = settings.get("contrast_factor", 1.0)
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(factor)
            logger.debug("Page %d: Applied contrast factor %f.", page_num, factor)
        if settings.get("enhance_brightness", False):
            factor = settings.get("brightness_factor", 1.0)
            enhancer = ImageEnhance.Brightness(img)
            img = enhancer.enhance(factor)
            logger.debug("Page %d: Applied brightness factor %f.", page_num, factor)
        if settings.get("sharpen", False):
            img = img.filter(ImageFilter.SHARPEN)
            logger.debug("Page %d: Applied sharpen.", page_num)

        output_format = "JPEG"
        jpeg_quality = settings.get("quality", 80)

        if settings.get("binarize", False):
            img = img.convert("L")
            threshold = settings.get("binarize_threshold", 128)
            img = img.point(lambda x: 0 if x < threshold else 255, "1")
            output_format = "PNG"
            logger.debug("Page %d: Applied binarization with threshold %d. Output: PNG.", page_num, threshold)
        elif settings.get("grayscale", False):
            img = img.convert("L")
            logger.debug("Page %d: Converted to grayscale.", page_num)

        img_byte_arr = io.BytesIO()
        if output_format == "JPEG":
            if img.mode not in ["RGB", "L"]:
                img = img.convert("RGB" if img.mode in ["P", "RGBA"] else "L")
            img.save(img_byte_arr, format="JPEG", quality=jpeg_quality, optimize=True)
        else:  # PNG
            img.save(img_byte_arr, format="PNG", optimize=True)
        img_bytes = img_byte_arr.getvalue()

        logger.debug(
            "Page %d successfully processed. Output format: %s, Size: %.2f KB",
            page_num,
            output_format,
            len(img_bytes) / 1024.0,
        )

        doc_to_close.close()
        return page_num, img_bytes, output_format, original_width, original_height

    except Exception as e:
        logger.error("Error processing page %d of '%s': %s", page_num, input_pdf_path, e, exc_info=True)
        if doc_to_close:
            try:
                doc_to_close.close()
            except:
                pass  # Silently ignore close error if already failed
        return page_num, None, None, None, None
