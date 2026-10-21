"""Markdown document loader parsing headings, paragraphs, and tables."""

import re
from pathlib import Path

from veltrix.ingestion.loaders.base import BaseLoader, DocumentElement, RawDocument
from veltrix.ingestion.manifest import ManifestItem


class MarkdownLoader(BaseLoader):
    """Loader for Markdown (.md) documents."""

    def load(self, file_path: Path, item: ManifestItem) -> RawDocument:
        with open(file_path, encoding="utf-8") as f:
            lines = f.readlines()

        elements: list[DocumentElement] = []
        current_locator = "p. 1"
        table_buffer: list[list[str]] = []
        paragraph_buffer: list[str] = []

        def flush_paragraph() -> None:
            if paragraph_buffer:
                text = "".join(paragraph_buffer).strip()
                if text:
                    elements.append(
                        DocumentElement(
                            element_type="paragraph",
                            text=text,
                            locator=current_locator,
                            page_num=1,
                        )
                    )
                paragraph_buffer.clear()

        def flush_table() -> None:
            if table_buffer:
                elements.append(
                    DocumentElement(
                        element_type="table",
                        text="",
                        locator=current_locator,
                        page_num=1,
                        table_rows=list(table_buffer),
                    )
                )
                table_buffer.clear()

        for line in lines:
            stripped = line.strip()

            # Check for headings
            heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
            if heading_match:
                flush_paragraph()
                flush_table()
                level = len(heading_match.group(1))
                heading_text = heading_match.group(2).strip()
                current_locator = heading_text
                elements.append(
                    DocumentElement(
                        element_type="heading",
                        text=heading_text,
                        locator=current_locator,
                        page_num=1,
                        heading_level=level,
                    )
                )
                continue

            # Check for table rows (| col 1 | col 2 |)
            if stripped.startswith("|") and stripped.endswith("|"):
                flush_paragraph()
                # Skip markdown separator row |---|---|
                cells = [c.strip() for c in stripped.split("|")[1:-1]]
                if all(re.match(r"^:?-+:?$", c) for c in cells if c):
                    continue
                table_buffer.append(cells)
                continue

            # If we were in a table and hit a non-table line
            if table_buffer:
                flush_table()

            # Blank line flushes paragraph
            if not stripped:
                flush_paragraph()
            else:
                paragraph_buffer.append(line)

        flush_paragraph()
        flush_table()

        return RawDocument(manifest_item=item, elements=elements)
