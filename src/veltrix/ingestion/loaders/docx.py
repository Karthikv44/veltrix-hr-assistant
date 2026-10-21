"""DOCX document loader iterating body elements in DOM order."""

from pathlib import Path

from docx import Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from veltrix.ingestion.loaders.base import BaseLoader, DocumentElement, RawDocument
from veltrix.ingestion.manifest import ManifestItem


class DocxLoader(BaseLoader):
    """Loader for Word DOCX documents preserving body element sequence."""

    def load(self, file_path: Path, item: ManifestItem) -> RawDocument:
        doc = Document(file_path)

        elements: list[DocumentElement] = []
        current_locator = "p. 1"

        # Iterate body elements in order so tables stay in place
        for child in doc.element.body:
            if isinstance(child, CT_P):
                p = Paragraph(child, doc)
                text = p.text.strip()
                if not text:
                    continue

                style_name = p.style.name.lower() if p.style else ""
                is_heading = style_name.startswith("heading") or (
                    any(run.bold for run in p.runs if run.text.strip()) and len(text) < 120
                )

                if is_heading:
                    current_locator = text
                    level = 1
                    if "heading 2" in style_name:
                        level = 2
                    elif "heading 3" in style_name:
                        level = 3
                    elements.append(
                        DocumentElement(
                            element_type="heading",
                            text=text,
                            locator=current_locator,
                            page_num=1,
                            heading_level=level,
                        )
                    )
                else:
                    elements.append(
                        DocumentElement(
                            element_type="paragraph",
                            text=text,
                            locator=current_locator,
                            page_num=1,
                        )
                    )

            elif isinstance(child, CT_Tbl):
                tbl = Table(child, doc)
                rows: list[list[str]] = []
                for row in tbl.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    # Deduplicate merged cells in row if needed
                    if any(cells):
                        rows.append(cells)

                if rows:
                    elements.append(
                        DocumentElement(
                            element_type="table",
                            text="",
                            locator=current_locator,
                            page_num=1,
                            table_rows=rows,
                        )
                    )

        return RawDocument(manifest_item=item, elements=elements)
