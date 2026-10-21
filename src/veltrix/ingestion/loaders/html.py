"""HTML document loader parsing headings, paragraphs, and tables."""

from pathlib import Path

from bs4 import BeautifulSoup, Tag

from veltrix.ingestion.loaders.base import BaseLoader, DocumentElement, RawDocument
from veltrix.ingestion.manifest import ManifestItem


class HtmlLoader(BaseLoader):
    """Loader for HTML documents using BeautifulSoup4."""

    def load(self, file_path: Path, item: ManifestItem) -> RawDocument:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()

        soup = BeautifulSoup(content, "lxml")

        # Remove scripts, styles, navigation, and header/footer boilerplate
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()

        elements: list[DocumentElement] = []
        current_locator = "p. 1"

        body = soup.body or soup

        # Iterate over top-level body tags to preserve order
        for child in body.children:
            if not isinstance(child, Tag):
                continue

            name = child.name.lower()

            if name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                text = child.get_text(separator=" ", strip=True)
                if text:
                    current_locator = text
                    level = int(name[1])
                    elements.append(
                        DocumentElement(
                            element_type="heading",
                            text=text,
                            locator=current_locator,
                            page_num=1,
                            heading_level=level,
                        )
                    )

            elif name == "table":
                rows: list[list[str]] = []
                for tr in child.find_all("tr"):
                    cells = [
                        c.get_text(separator=" ", strip=True) for c in tr.find_all(["th", "td"])
                    ]
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

            elif name in ["p", "ul", "ol", "div", "section", "article"]:
                text = child.get_text(separator="\n", strip=True)
                if text:
                    # In FAQ pages, check if this element looks like a Q&A block
                    elements.append(
                        DocumentElement(
                            element_type="paragraph",
                            text=text,
                            locator=current_locator,
                            page_num=1,
                        )
                    )

        return RawDocument(manifest_item=item, elements=elements)
