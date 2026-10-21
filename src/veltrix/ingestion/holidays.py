"""Deterministic holiday table extractor for calendar documents."""

import re
import sqlite3
from datetime import date

from dateutil import parser as date_parser

from veltrix.core.logging import get_logger
from veltrix.domain.models import Holiday
from veltrix.ingestion.loaders.base import DocumentElement
from veltrix.ingestion.manifest import ManifestItem

logger = get_logger("holidays")

# Months regex to insert missing spaces in PDF extracted dates like "15January2026"
MONTH_SPLIT_REGEX = re.compile(
    r"(\d+)\s*(January|February|March|April|May|June|July|August|September|October|November|December)\s*(\d*)",
    re.IGNORECASE,
)


def normalize_date_string(raw: str, default_year: str) -> str:
    """Normalize date text (e.g. '15January2026' -> '15 January 2026')."""
    cleaned = re.sub(r"[\r\n\t]+", " ", raw).strip()

    match = MONTH_SPLIT_REGEX.search(cleaned)
    if match:
        day = match.group(1)
        month = match.group(2)
        year = match.group(3) or default_year
        return f"{day} {month} {year}"

    # If no year in string, append default year
    if not re.search(r"\b20\d\d\b", cleaned):
        cleaned = f"{cleaned} {default_year}"

    return cleaned


def extract_holidays_from_table(table: DocumentElement, item: ManifestItem) -> list[Holiday]:
    """Parse a single table element from a calendar document into Holiday records."""
    rows = table.table_rows
    if not rows or len(rows) < 2:
        return []

    header = [c.strip().lower() for c in rows[0]]

    # Identify date and holiday columns
    date_col = -1
    name_col = -1
    is_optional_table = False

    for idx, col in enumerate(header):
        if "date" in col or "datum" in col:
            date_col = idx
        elif "holiday" in col or "feiertag" in col or "name" in col:
            name_col = idx
            if "restricted" in col or "optional" in col:
                is_optional_table = True

    # If header didn't match, check if second row or caption specifies
    if date_col == -1 or name_col == -1:
        return []

    default_year = item.effective_date[:4]
    holidays: list[Holiday] = []
    region = item.regions[0] if item.regions else "GLOBAL"

    for row in rows[1:]:
        if len(row) <= max(date_col, name_col):
            continue

        raw_date = row[date_col].strip()
        raw_name = re.sub(r"[\r\n]+", " ", row[name_col]).strip()

        if not raw_date or not raw_name:
            continue

        norm_date_str = normalize_date_string(raw_date, default_year)

        try:
            parsed_dt = date_parser.parse(norm_date_str, dayfirst=True)
            holiday_date = date(parsed_dt.year, parsed_dt.month, parsed_dt.day)

            kind = "optional" if is_optional_table else "public"
            holidays.append(
                Holiday(
                    doc_id=item.doc_id,
                    date=holiday_date,
                    name=raw_name,
                    kind=kind,
                    region=region,
                )
            )
        except Exception as e:
            logger.debug(
                "Skipping unparseable holiday row",
                raw_date=raw_date,
                norm_date=norm_date_str,
                error=str(e),
            )

    return holidays


def extract_and_store_holidays(
    elements: list[DocumentElement], item: ManifestItem, app_db_path: str
) -> list[Holiday]:
    """Extract holidays from all calendar tables in a document and save to SQLite app.db."""
    if item.doc_type != "calendar":
        return []

    all_holidays: list[Holiday] = []
    for el in elements:
        if el.element_type == "table":
            extracted = extract_holidays_from_table(el, item)
            all_holidays.extend(extracted)

    if not all_holidays:
        logger.warning("No holidays extracted for calendar document", doc_id=item.doc_id)
        return []

    # Save to app.db
    conn = sqlite3.connect(app_db_path)
    try:
        with conn:
            # Clear previous holidays for this doc_id to ensure idempotency
            conn.execute("DELETE FROM holidays WHERE doc_id = ?", (item.doc_id,))
            for h in all_holidays:
                conn.execute(
                    """
                    INSERT INTO holidays (doc_id, date, name, kind, region)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (h.doc_id, h.date.isoformat(), h.name, h.kind, h.region),
                )
        logger.info(
            "Extracted and stored holidays",
            doc_id=item.doc_id,
            region=item.regions,
            count=len(all_holidays),
            public_count=sum(1 for h in all_holidays if h.kind == "public"),
            optional_count=sum(1 for h in all_holidays if h.kind == "optional"),
        )
    finally:
        conn.close()

    return all_holidays
