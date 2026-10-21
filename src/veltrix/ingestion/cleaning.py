"""Text cleaning and boilerplate removal: metadata tables, repeated headers/footers, and noise."""

import re

from veltrix.core.logging import get_logger
from veltrix.ingestion.loaders.base import DocumentElement
from veltrix.ingestion.manifest import ManifestItem

logger = get_logger("cleaning")

# Regex to detect page number noise
PAGE_NOISE_REGEX = re.compile(
    r"^(?:page\s*\d+(?:\s*of\s*\d+)?|\d+\s*/\s*\d+|[-–—]\s*\d+\s*[-–—]|\d+)$",
    re.IGNORECASE,
)

# Common metadata labels in document header tables
METADATA_LABELS = {
    "document id",
    "doc id",
    "effective date",
    "version",
    "author",
    "owner",
    "classification",
    "access level",
    "regions",
    "applies to",
}


def is_metadata_table(element: DocumentElement, manifest_item: ManifestItem) -> bool:
    """Check if a table element at the beginning of a document is an in-document metadata block."""
    if element.element_type != "table" or not element.table_rows:
        return False

    # Flatten all cell texts
    cells = [cell.strip().lower() for row in element.table_rows for cell in row if cell]
    matching_labels = sum(1 for label in METADATA_LABELS if any(label in c for c in cells))

    # If 2 or more standard metadata field names appear in this table
    if matching_labels >= 2:
        # Check if internal doc_id differs from manifest
        for row in element.table_rows:
            for cell in row:
                if "POL-" in cell or "ADD-" in cell or "MEMO-" in cell:
                    internal_id = cell.strip()
                    if internal_id != manifest_item.doc_id:
                        logger.warning(
                            "In-document doc_id disagrees with manifest",
                            manifest_doc_id=manifest_item.doc_id,
                            in_doc_id=internal_id,
                        )
        return True

    return False


def is_page_noise(line: str) -> bool:
    """Check if a single line of text is purely page number noise."""
    s = line.strip()
    return bool(PAGE_NOISE_REGEX.match(s))


def strip_repeated_headers_footers(
    elements: list[DocumentElement], total_pages: int
) -> list[DocumentElement]:
    """Detect and remove lines repeating across multiple pages in header or footer positions."""
    if total_pages <= 1:
        return elements

    # Collect line frequencies across pages
    line_page_map: dict[str, set[int]] = {}
    for el in elements:
        if el.element_type == "paragraph":
            lines = [ln.strip() for ln in el.text.splitlines() if ln.strip()]
            for ln in lines:
                if len(ln) < 100:  # Headers/footers are usually short
                    line_page_map.setdefault(ln, set()).add(el.page_num)

    # Lines appearing on more than half the pages are boilerplate
    threshold = max(2, total_pages // 2)
    repeated_lines = {ln for ln, pages in line_page_map.items() if len(pages) >= threshold}

    cleaned_elements: list[DocumentElement] = []
    for el in elements:
        if el.element_type == "paragraph":
            cleaned_lines = [
                ln
                for ln in el.text.splitlines()
                if ln.strip() not in repeated_lines and not is_page_noise(ln)
            ]
            cleaned_text = "\n".join(cleaned_lines).strip()
            if cleaned_text:
                el.text = cleaned_text
                cleaned_elements.append(el)
        else:
            cleaned_elements.append(el)

    return cleaned_elements


def clean_document_elements(
    elements: list[DocumentElement], manifest_item: ManifestItem, total_pages: int
) -> list[DocumentElement]:
    """Clean all elements in a raw document: remove metadata tables and repeated headers/footers."""
    # 1. Filter out metadata table at top of document
    filtered: list[DocumentElement] = []
    found_metadata_table = False

    for idx, el in enumerate(elements):
        if idx < 3 and not found_metadata_table and is_metadata_table(el, manifest_item):
            logger.info("Stripped in-document metadata table", doc_id=manifest_item.doc_id)
            found_metadata_table = True
            continue
        filtered.append(el)

    # 2. Strip repeated headers, footers, and page number noise
    return strip_repeated_headers_footers(filtered, total_pages)
