"""Reciprocal Rank Fusion (RRF) and doc_id diversity grouping."""

from collections import defaultdict

from veltrix.core.logging import get_logger

logger = get_logger("fusion")


def reciprocal_rank_fusion(
    dense_results: list[tuple[str, float]],
    lexical_results: list[tuple[str, float]],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Combine dense and lexical ranked results using Reciprocal Rank Fusion (RRF).

    Formula: RRF_score(d) = sum(1.0 / (k + rank_i(d)))
    Deterministic tie-break on score, then chunk_id.
    """
    scores: dict[str, float] = defaultdict(float)

    for rank, (cid, _score) in enumerate(dense_results, start=1):
        scores[cid] += 1.0 / (k + rank)

    for rank, (cid, _score) in enumerate(lexical_results, start=1):
        scores[cid] += 1.0 / (k + rank)

    # Sort descending by fused score, then ascending by chunk_id for deterministic tie-break
    fused = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
    return fused


def group_by_doc_id(
    fused_results: list[tuple[str, float]],
    chunk_doc_map: dict[str, str],
    max_chunks_per_doc: int = 2,
    limit: int = 15,
) -> list[str]:
    """Group fused results by doc_id allowing up to max_chunks_per_doc per document.

    Ensures competing versions of the same policy/document are both retrieved
    so the deterministic precedence engine can decide.
    """
    doc_counts: dict[str, int] = defaultdict(int)
    selected_chunk_ids: list[str] = []

    for cid, _score in fused_results:
        doc_id = chunk_doc_map.get(cid)
        if not doc_id:
            continue

        if doc_counts[doc_id] < max_chunks_per_doc:
            doc_counts[doc_id] += 1
            selected_chunk_ids.append(cid)
            if len(selected_chunk_ids) >= limit:
                break

    return selected_chunk_ids
