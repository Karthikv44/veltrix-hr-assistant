"""OCR processing engine using Tesseract with Pillow image preprocessing."""

import os
import shutil
from pathlib import Path
from typing import Any

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter

from veltrix.core.logging import get_logger

logger = get_logger("ocr")


def configure_tesseract() -> None:
    """Locate and configure the Tesseract executable across environments."""
    configured_cmd = getattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract")
    if shutil.which(configured_cmd):
        return

    # Check common system paths on Windows and Linux
    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
    ]
    for path in candidates:
        if Path(path).exists():
            pytesseract.pytesseract.tesseract_cmd = path
            logger.info("Configured Tesseract path", path=path)
            return

    logger.warning("Tesseract binary not found in standard paths; OCR may fail if invoked.")


# Ensure tesseract is configured upon module import
configure_tesseract()


def preprocess_image_for_ocr(image: Image.Image) -> Image.Image:
    """Preprocess image for optimal OCR: grayscale, contrast enhancement, and slight sharpen."""
    # Convert to grayscale
    gray = image.convert("L")

    # Increase contrast
    enhancer = ImageEnhance.Contrast(gray)
    contrasted = enhancer.enhance(1.8)

    # Slight filter to sharpen text edges
    sharpened = contrasted.filter(ImageFilter.SHARPEN)
    return sharpened


def ocr_image(image: Image.Image) -> str:
    """Execute Tesseract OCR on a PIL image returning cleaned string text."""
    configure_tesseract()
    preprocessed = preprocess_image_for_ocr(image)
    text = pytesseract.image_to_string(preprocessed, config="--psm 1 --oem 3")
    return text.strip()


def ocr_image_tsv(image: Image.Image) -> list[dict[str, Any]]:
    """Execute Tesseract OCR with TSV output containing word coordinates and confidences."""
    configure_tesseract()
    preprocessed = preprocess_image_for_ocr(image)
    data = pytesseract.image_to_data(
        preprocessed, output_type=pytesseract.Output.DICT, config="--psm 1 --oem 3"
    )

    rows: list[dict[str, Any]] = []
    n_boxes = len(data["text"])
    for i in range(n_boxes):
        word = data["text"][i].strip()
        if word:
            rows.append(
                {
                    "text": word,
                    "conf": float(data["conf"][i]),
                    "left": data["left"][i],
                    "top": data["top"][i],
                    "width": data["width"][i],
                    "height": data["height"][i],
                    "line_num": data["line_num"][i],
                    "block_num": data["block_num"][i],
                }
            )
    return rows
