"""Unit tests for chunker, cleaning, tables, and holiday extraction."""

import sqlite3
from datetime import date
from pathlib import Path

from veltrix.data.db import init_app_db
from veltrix.ingestion.chunker import DocumentChunker
from veltrix.ingestion.cleaning import clean_document_elements, is_page_noise
from veltrix.ingestion.holidays import extract_and_store_holidays
from veltrix.ingestion.loaders.base import DocumentElement
from veltrix.ingestion.manifest import ManifestItem
from veltrix.ingestion.tables import format_table_as_markdown, split_table_rows_if_needed


def test_format_table_as_markdown() -> None:
    rows = [
        ["Header 1", "Header 2"],
        ["Val A", "Val B"],
    ]
    md = format_table_as_markdown(rows, caption="Sample Table")
    assert "### Sample Table" in md
    assert "| Header 1 | Header 2 |" in md
    assert "| Val A | Val B |" in md


def test_split_table_rows() -> None:
    rows = [["H1", "H2"]] + [[f"V{i}", f"W{i}"] for i in range(10)]
    splits = split_table_rows_if_needed(rows, max_rows_per_chunk=4)
    assert len(splits) == 3
    # Each split must preserve header
    for s in splits:
        assert s[0] == ["H1", "H2"]


def test_page_noise_detection() -> None:
    assert is_page_noise("Page 1 of 5")
    assert is_page_noise("12 / 30")
    assert is_page_noise("- 4 -")
    assert not is_page_noise("1. Working Hours")


def test_clean_document_elements_strips_metadata_table() -> None:
    manifest_item = ManifestItem(
        doc_id="POL-LEAVE-01",
        file="leave.pdf",
        title="Leave Policy",
        doc_type="policy",
        regions=["GLOBAL"],
        effective_date="2026-01-01",
        access_level="all",
    )
    elements = [
        DocumentElement(
            element_type="table",
            text="",
            locator="p. 1",
            table_rows=[
                ["Document ID", "POL-LEAVE-01"],
                ["Effective date", "2026-01-01"],
                ["Classification", "All"],
            ],
        ),
        DocumentElement(
            element_type="paragraph",
            text="Actual policy content.",
            locator="1. Introduction",
        ),
    ]
    cleaned = clean_document_elements(elements, manifest_item, total_pages=1)
    # Metadata table at start is removed
    assert len(cleaned) == 1
    assert cleaned[0].text == "Actual policy content."


def test_chunker_section_splitting_and_context_headers() -> None:
    manifest_item = ManifestItem(
        doc_id="POL-BENEFITS",
        file="benefits.md",
        title="Benefits Policy",
        doc_type="policy",
        regions=["GLOBAL"],
        effective_date="2026-01-01",
        access_level="all",
    )
    elements = [
        DocumentElement(
            element_type="heading", text="1. Health Insurance", locator="1. Health Insurance"
        ),
        DocumentElement(
            element_type="paragraph",
            text="Coverage includes medical and dental.",
            locator="1. Health Insurance",
        ),
        DocumentElement(
            element_type="heading", text="2. Retirement Plans", locator="2. Retirement Plans"
        ),
        DocumentElement(
            element_type="paragraph",
            text="Matching contributions up to 5%.",
            locator="2. Retirement Plans",
        ),
    ]

    chunker = DocumentChunker()
    chunks = chunker.chunk_document(elements, manifest_item)
    assert len(chunks) == 2
    assert "Benefits Policy > 1. Health Insurance" in chunks[0].embedded_text
    assert "Benefits Policy > 2. Retirement Plans" in chunks[1].embedded_text
    assert chunks[0].metadata["doc_id"] == "POL-BENEFITS"
    assert chunks[0].metadata["region_GLOBAL"] is True


def test_extract_and_store_holidays(tmp_path: Path) -> None:
    app_db = tmp_path / "test_app.db"
    init_app_db(app_db)

    item = ManifestItem(
        doc_id="CAL-TEST-2026",
        file="cal.pdf",
        title="Holiday Calendar 2026",
        doc_type="calendar",
        regions=["IN"],
        effective_date="2026-01-01",
        access_level="all",
    )
    table_el = DocumentElement(
        element_type="table",
        text="",
        locator="p. 1",
        table_rows=[
            ["Date", "Day", "Holiday"],
            ["26 January 2026", "Monday", "Republic Day"],
            ["15 August 2026", "Saturday", "Independence Day"],
        ],
    )

    holidays = extract_and_store_holidays([table_el], item, str(app_db))
    assert len(holidays) == 2
    assert holidays[0].name == "Republic Day"
    assert holidays[0].date == date(2026, 1, 26)
    assert holidays[0].kind == "public"

    # Verify saved in SQLite
    conn = sqlite3.connect(app_db)
    rows = conn.execute("SELECT doc_id, date, name, kind, region FROM holidays").fetchall()
    conn.close()
    assert len(rows) == 2
    assert rows[0][0] == "CAL-TEST-2026"
    assert rows[0][1] == "2026-01-26"
    assert rows[0][4] == "IN"
