"""Greedy evidence packer enforcing the 2,800 token budget with exact delimiter accounting."""

from veltrix.core.tokens import count_tokens
from veltrix.ingestion.chunker import Chunk


def format_chunk_passage(chunk: Chunk) -> str:
    """Format a chunk with clear doc_id and locator delimiters for evidence packing."""
    return f"[DOCUMENT: {chunk.doc_id} | LOCATOR: {chunk.locator}]\n{chunk.text}\n[/DOCUMENT]"


def pack_evidence(
    chunks: list[Chunk],
    max_budget_tokens: int = 2800,
) -> tuple[str, list[Chunk], int]:
    """Greedily pack chunks into a single evidence block strictly within max_budget_tokens.

    Counts EXACTLY the text that will be sent, including per-chunk headers and delimiters.

    Returns:
        (packed_evidence_text, packed_chunks, total_tokens)
    """
    packed_passages: list[str] = []
    packed_chunks: list[Chunk] = []
    total_tokens = 0

    for chunk in chunks:
        passage = format_chunk_passage(chunk)
        # Account for double newline joiner if already have passages
        candidate_text = "\n\n".join(packed_passages + [passage]) if packed_passages else passage
        candidate_tokens = count_tokens(candidate_text)

        if candidate_tokens <= max_budget_tokens:
            packed_passages.append(passage)
            packed_chunks.append(chunk)
            total_tokens = candidate_tokens
        else:
            # Stop packing once budget cannot accommodate next passage
            continue

    final_text = "\n\n".join(packed_passages)
    return final_text, packed_chunks, total_tokens
