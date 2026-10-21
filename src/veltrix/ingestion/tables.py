"""Table formatting, markdown serialization, and row splitting utilities."""

import re

HEADER_SEPARATOR = "---"


def clean_cell_text(text: str) -> str:
    """Clean newlines and pipes from cell text."""
    if not text:
        return ""
    # Replace newlines with spaces and escape pipes
    cleaned = re.sub(r"[\r\n]+", " ", str(text)).strip()
    return cleaned.replace("|", "\\|")


def format_table_as_markdown(rows: list[list[str]], caption: str | None = None) -> str:
    """Serialize a 2D list of strings into a standard Markdown table."""
    if not rows or not any(rows):
        return ""

    # Ensure rectangular grid
    num_cols = max(len(row) for row in rows)
    normalized_rows = [
        [clean_cell_text(cell) if i < len(row) else "" for i, cell in enumerate(row)]
        + [""] * (num_cols - len(row))
        for row in rows
    ]

    header = normalized_rows[0]
    separator = [HEADER_SEPARATOR] * num_cols
    data_rows = normalized_rows[1:]

    lines: list[str] = []
    if caption:
        lines.append(f"### {caption.strip()}\n")

    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(separator) + " |")
    for row in data_rows:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def split_table_rows_if_needed(
    rows: list[list[str]], max_rows_per_chunk: int = 25
) -> list[list[list[str]]]:
    """Split very large tables into chunks of rows, repeating the header in each chunk."""
    if not rows or len(rows) <= 1:
        return [rows] if rows else []

    header = rows[0]
    data_rows = rows[1:]

    if len(data_rows) <= max_rows_per_chunk:
        return [rows]

    chunks: list[list[list[str]]] = []
    for i in range(0, len(data_rows), max_rows_per_chunk):
        slice_rows = [header] + data_rows[i : i + max_rows_per_chunk]
        chunks.append(slice_rows)

    return chunks
