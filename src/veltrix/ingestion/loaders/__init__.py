"""Document loader registry and default format registrations."""

from veltrix.ingestion.loaders.base import BaseLoader, DocumentElement, RawDocument
from veltrix.ingestion.loaders.docx import DocxLoader
from veltrix.ingestion.loaders.html import HtmlLoader
from veltrix.ingestion.loaders.markdown import MarkdownLoader
from veltrix.ingestion.loaders.pdf import PdfLoader
from veltrix.ingestion.loaders.registry import LoaderRegistry, loader_registry, register_loader

# Register standard formats
loader_registry.register(".pdf", PdfLoader)
loader_registry.register(".docx", DocxLoader)
loader_registry.register(".md", MarkdownLoader)
loader_registry.register(".html", HtmlLoader)
loader_registry.register(".htm", HtmlLoader)

__all__ = [
    "BaseLoader",
    "DocxLoader",
    "DocumentElement",
    "HtmlLoader",
    "LoaderRegistry",
    "MarkdownLoader",
    "PdfLoader",
    "RawDocument",
    "loader_registry",
    "register_loader",
]
