"""PDF document loader with per-page text layer verification, table extraction, and OCR."""

import io
from pathlib import Path

import pymupdf
from PIL import Image

from veltrix.core.logging import get_logger
from veltrix.ingestion.loaders.base import BaseLoader, DocumentElement, RawDocument
from veltrix.ingestion.loaders.ocr import ocr_image
from veltrix.ingestion.manifest import ManifestItem

logger = get_logger("pdf_loader")


class PdfLoader(BaseLoader):
    """Loader for PDF documents with per-page OCR fallback and table extraction."""

    def load(self, file_path: Path, item: ManifestItem) -> RawDocument:
        doc = pymupdf.open(str(file_path))
        elements: list[DocumentElement] = []
        current_locator = "p. 1"

        for page_idx in range(len(doc)):
            page_num = page_idx + 1
            page = doc[page_idx]

            raw_text = page.get_text("text").strip()

            # 1. Per-page text layer verification: OCR if missing or near-empty
            if len(raw_text) < 50:
                logger.info(
                    "PDF page has no text layer; running OCR at 300 DPI",
                    file=file_path.name,
                    page=page_num,
                )
                pix = page.get_pixmap(dpi=300)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                ocr_text = ocr_image(img)

                # Parse lines from OCR
                ocr_lines = [ln.strip() for ln in ocr_text.splitlines() if ln.strip()]
                for ln in ocr_lines:
                    # Check if line looks like a title or heading
                    if ln.isupper() and len(ln) < 80:
                        current_locator = ln
                        elements.append(
                            DocumentElement(
                                element_type="heading",
                                text=ln,
                                locator=current_locator,
                                page_num=page_num,
                                heading_level=1,
                            )
                        )
                    else:
                        elements.append(
                            DocumentElement(
                                element_type="paragraph",
                                text=ln,
                                locator=current_locator,
                                page_num=page_num,
                            )
                        )
                continue

            # 2. Extract tables on this page
            page_tables: list[list[list[str]]] = []
            try:
                tables = page.find_tables()
                for tbl in tables:
                    extracted = tbl.extract()
                    cleaned_rows = [
                        [c.strip() if c else "" for c in row] for row in extracted if any(row)
                    ]
                    if cleaned_rows:
                        page_tables.append(cleaned_rows)
            except Exception as e:
                logger.debug("Table detection error on page", page=page_num, error=str(e))

            # 3. Extract text blocks with font sizes for heading detection
            blocks = page.get_text("dict")["blocks"]
            font_sizes: list[float] = []
            for b in blocks:
                if "lines" in b:
                    for line in b["lines"]:
                        for span in line["spans"]:
                            if span["text"].strip():
                                font_sizes.append(span["size"])

            avg_size = (sum(font_sizes) / len(font_sizes)) if font_sizes else 11.0

            # Iterate blocks
            for b in blocks:
                if "lines" not in b:
                    continue

                block_lines: list[str] = []
                max_span_size = 0.0
                is_bold = False

                for line in b["lines"]:
                    line_text = "".join(span["text"] for span in line["spans"]).strip()
                    if line_text:
                        block_lines.append(line_text)
                        for span in line["spans"]:
                            max_span_size = max(max_span_size, span["size"])
                            if "bold" in span["font"].lower():
                                is_bold = True

                block_text = " ".join(block_lines).strip()
                if not block_text:
                    continue

                # Heading detection: font size meaningfully larger than avg, or bold + short
                is_heading = (max_span_size >= avg_size + 1.8 and len(block_text) < 120) or (
                    is_bold and len(block_text) < 80 and not block_text.endswith(".")
                )

                if is_heading:
                    current_locator = block_text
                    level = 1 if max_span_size >= avg_size + 3.0 else 2
                    elements.append(
                        DocumentElement(
                            element_type="heading",
                            text=block_text,
                            locator=current_locator,
                            page_num=page_num,
                            heading_level=level,
                        )
                    )
                else:
                    elements.append(
                        DocumentElement(
                            element_type="paragraph",
                            text=block_text,
                            locator=current_locator or f"p. {page_num}",
                            page_num=page_num,
                        )
                    )

            # Add extracted tables for this page
            for tbl_rows in page_tables:
                elements.append(
                    DocumentElement(
                        element_type="table",
                        text="",
                        locator=current_locator or f"p. {page_num}",
                        page_num=page_num,
                        table_rows=tbl_rows,
                    )
                )

        doc.close()
        return RawDocument(manifest_item=item, elements=elements)
