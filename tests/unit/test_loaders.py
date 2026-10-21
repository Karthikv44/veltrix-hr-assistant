"""Unit tests for document loaders (PDF, DOCX, Markdown, HTML) and registry extensibility."""

from pathlib import Path

import pytest

from tests.fixtures.builders import (
    create_docx_fixture,
    create_html_fixture,
    create_markdown_fixture,
    create_pdf_fixture,
)
from veltrix.ingestion.loaders.base import BaseLoader, DocumentElement, RawDocument
from veltrix.ingestion.loaders.registry import LoaderRegistry, loader_registry
from veltrix.ingestion.manifest import ManifestItem


@pytest.fixture
def sample_item() -> ManifestItem:
    return ManifestItem(
        doc_id="POL-TEST-001",
        file="test.md",
        title="Test Policy Title",
        doc_type="policy",
        regions=["GLOBAL"],
        effective_date="2026-01-01",
        access_level="all",
    )


def test_markdown_loader(tmp_path: Path, sample_item: ManifestItem) -> None:
    file_path = tmp_path / "test.md"
    create_markdown_fixture(
        file_path,
        title="Remote Work Guidelines",
        sections=[("1. Eligibility", "All employees can request remote work.")],
        table=[["Col1", "Col2"], ["ValA", "ValB"]],
    )

    loader = loader_registry.get(".md")
    raw = loader.load(file_path, sample_item)
    assert len(raw.elements) >= 3
    types = [e.element_type for e in raw.elements]
    assert "heading" in types
    assert "paragraph" in types
    assert "table" in types


def test_html_loader(tmp_path: Path, sample_item: ManifestItem) -> None:
    file_path = tmp_path / "test.html"
    create_html_fixture(
        file_path,
        title="FAQ Answers",
        sections=[("How do I apply?", "Submit via self service.")],
        table=[["HeaderA", "HeaderB"], ["Row1A", "Row1B"]],
    )

    loader = loader_registry.get(".html")
    raw = loader.load(file_path, sample_item)
    assert len(raw.elements) >= 3
    locators = [e.locator for e in raw.elements]
    assert any("How do I apply?" in loc for loc in locators)


def test_docx_loader(tmp_path: Path, sample_item: ManifestItem) -> None:
    file_path = tmp_path / "test.docx"
    create_docx_fixture(
        file_path,
        title="Handbook Docx",
        sections=[("Section One", "Docx body element text.")],
        table=[["ColA", "ColB"], ["DataA", "DataB"]],
    )

    loader = loader_registry.get(".docx")
    raw = loader.load(file_path, sample_item)
    assert len(raw.elements) >= 2


def test_pdf_loader(tmp_path: Path, sample_item: ManifestItem) -> None:
    file_path = tmp_path / "test.pdf"
    create_pdf_fixture(
        file_path,
        title="PDF Policy",
        sections=[("1. Working Hours", "Core hours are 9 to 5.")],
    )

    loader = loader_registry.get(".pdf")
    raw = loader.load(file_path, sample_item)
    assert len(raw.elements) >= 1
    assert any("Working Hours" in e.text for e in raw.elements)


def test_extensibility_custom_format_loader(sample_item: ManifestItem, tmp_path: Path) -> None:
    """Extensibility acceptance test: adding a new format requires only a new class + one register call."""
    custom_reg = LoaderRegistry()

    class CustomXmlLoader(BaseLoader):
        def load(self, file_path: Path, item: ManifestItem) -> RawDocument:
            return RawDocument(
                manifest_item=item,
                elements=[
                    DocumentElement(
                        element_type="paragraph",
                        text="Custom XML content",
                        locator="p. 1",
                    )
                ],
            )

    # One registration line
    custom_reg.register(".customxml", CustomXmlLoader)

    test_file = tmp_path / "dummy.customxml"
    test_file.write_text("<root></root>")

    retrieved_loader = custom_reg.get(test_file)
    raw = retrieved_loader.load(test_file, sample_item)
    assert len(raw.elements) == 1
    assert raw.elements[0].text == "Custom XML content"
