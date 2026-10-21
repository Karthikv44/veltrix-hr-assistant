"""Document chunking on section boundaries with token bounds and context headers."""

from dataclasses import dataclass, field
from typing import Any

from veltrix.core.tokens import count_tokens
from veltrix.ingestion.loaders.base import DocumentElement
from veltrix.ingestion.manifest import ManifestItem
from veltrix.ingestion.tables import format_table_as_markdown, split_table_rows_if_needed


@dataclass
class Chunk:
    """Indexed text chunk with metadata and context header."""

    chunk_id: str
    doc_id: str
    text: str
    embedded_text: str
    locator: str
    token_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


class DocumentChunker:
    """Splits structured document elements into token-bounded chunks."""

    def __init__(
        self,
        target_tokens_min: int = 250,
        target_tokens_max: int = 350,
        hard_cap_tokens: int = 450,
    ) -> None:
        self.target_tokens_min = target_tokens_min
        self.target_tokens_max = target_tokens_max
        self.hard_cap_tokens = hard_cap_tokens

    def chunk_document(
        self,
        elements: list[DocumentElement],
        manifest_item: ManifestItem,
        all_known_regions: set[str] | None = None,
    ) -> list[Chunk]:
        """Convert document elements into Chunks with context headers and token counts."""
        base_meta = manifest_item.to_scalar_metadata(all_known_regions)
        chunks: list[Chunk] = []
        chunk_idx = 0

        current_heading = manifest_item.title
        current_locator = "p. 1"
        current_text_parts: list[str] = []

        def make_chunk_id() -> str:
            nonlocal chunk_idx
            cid = f"{manifest_item.doc_id}_c{chunk_idx:03d}"
            chunk_idx += 1
            return cid

        def flush_current_parts() -> None:
            if not current_text_parts:
                return
            combined_text = "\n\n".join(current_text_parts).strip()
            if not combined_text:
                current_text_parts.clear()
                return

            tokens = count_tokens(combined_text)
            # Context header: Title > Section
            context_header = f"{manifest_item.title} > {current_heading}"
            embedded_text = f"{context_header}\n\n{combined_text}"

            meta = dict(base_meta)
            meta["locator"] = current_locator
            meta["token_count"] = tokens

            chunks.append(
                Chunk(
                    chunk_id=make_chunk_id(),
                    doc_id=manifest_item.doc_id,
                    text=combined_text,
                    embedded_text=embedded_text,
                    locator=current_locator,
                    token_count=tokens,
                    metadata=meta,
                )
            )
            current_text_parts.clear()

        for el in elements:
            if el.element_type == "heading":
                # Headings define section boundaries
                flush_current_parts()
                current_heading = el.text
                current_locator = el.locator
                continue

            if el.element_type == "table":
                # Tables are emitted as standalone chunks or row groups
                flush_current_parts()
                if not el.table_rows:
                    continue

                # Split large tables by rows if needed
                table_splits = split_table_rows_if_needed(el.table_rows, max_rows_per_chunk=20)
                for tbl_group in table_splits:
                    table_md = format_table_as_markdown(tbl_group, caption=el.locator)
                    tokens = count_tokens(table_md)
                    context_header = f"{manifest_item.title} > {current_heading}"
                    embedded_text = f"{context_header}\n\n{table_md}"

                    meta = dict(base_meta)
                    meta["locator"] = el.locator
                    meta["token_count"] = tokens

                    chunks.append(
                        Chunk(
                            chunk_id=make_chunk_id(),
                            doc_id=manifest_item.doc_id,
                            text=table_md,
                            embedded_text=embedded_text,
                            locator=el.locator,
                            token_count=tokens,
                            metadata=meta,
                        )
                    )
                continue

            # Paragraph or FAQ QA
            text = el.text.strip()
            if not text:
                continue

            current_locator = el.locator
            candidate_tokens = count_tokens(text)

            # If single paragraph exceeds hard cap, emit by sentences/lines
            if candidate_tokens > self.hard_cap_tokens:
                flush_current_parts()
                lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
                sub_parts: list[str] = []
                for ln in lines:
                    ln_tokens = count_tokens(ln)
                    curr_tokens = count_tokens("\n".join(sub_parts))
                    if sub_parts and (curr_tokens + ln_tokens > self.target_tokens_max):
                        current_text_parts = list(sub_parts)
                        flush_current_parts()
                        sub_parts = [ln]
                    else:
                        sub_parts.append(ln)
                if sub_parts:
                    current_text_parts = list(sub_parts)
                    flush_current_parts()
                continue

            # Check accumulated tokens
            accumulated_tokens = count_tokens("\n\n".join(current_text_parts + [text]))
            if accumulated_tokens > self.target_tokens_max and current_text_parts:
                flush_current_parts()

            current_text_parts.append(text)

        flush_current_parts()
        return chunks
