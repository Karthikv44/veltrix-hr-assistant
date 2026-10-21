"""Base document element and loader abstractions."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from veltrix.ingestion.manifest import ManifestItem

ElementType = Literal["heading", "paragraph", "table", "faq_qa"]


@dataclass
class DocumentElement:
    """Atomic content element extracted from a raw document."""

    element_type: ElementType
    text: str
    locator: str  # Nearest heading (e.g. "1. Working hours" or "p. 3")
    page_num: int = 1
    heading_level: int = 0
    table_rows: list[list[str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawDocument:
    """Complete document extracted into structured elements."""

    manifest_item: ManifestItem
    elements: list[DocumentElement]


class BaseLoader(ABC):
    """Abstract base class for document format loaders."""

    @abstractmethod
    def load(self, file_path: Path, item: ManifestItem) -> RawDocument:
        """Parse the file into structured document elements."""
        ...
