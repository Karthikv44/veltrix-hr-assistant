"""Unit tests for retrieval scope, BM25 filtering, RRF fusion, and greedy packing."""

from datetime import date

from veltrix.domain.models import RequestContext
from veltrix.ingestion.chunker import Chunk
from veltrix.retrieval.fusion import group_by_doc_id, reciprocal_rank_fusion
from veltrix.retrieval.packer import pack_evidence
from veltrix.retrieval.scope import (
    ScopeViolationError,
    assert_all_eligible,
    build_scope,
)


def make_dummy_chunk(
    chunk_id: str,
    doc_id: str,
    access_rank: int = 0,
    region_in: bool = True,
    region_global: bool = False,
    effective_int: int = 20260101,
    token_count: int = 50,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        text=f"Text content for {chunk_id}",
        embedded_text=f"Title > Section\n\nText content for {chunk_id}",
        locator="1. Section",
        token_count=token_count,
        metadata={
            "doc_id": doc_id,
            "access_rank": access_rank,
            "region_IN": region_in,
            "region_GLOBAL": region_global,
            "region_US": False,
            "region_DE": False,
            "effective_int": effective_int,
        },
    )


def test_scope_building_and_eligibility() -> None:
    ctx = RequestContext(employee_id="E1001", role="employee", region="IN")
    scope = build_scope(ctx, date(2026, 6, 1))
    assert scope.role_rank == 0
    assert scope.ref_int == 20260601

    # Employee cannot access managers chunk
    manager_chunk = make_dummy_chunk("c1", "DOC1", access_rank=1, region_in=True)
    assert not scope.is_chunk_eligible(manager_chunk)

    # Employee can access all-level IN chunk
    employee_chunk = make_dummy_chunk(
        "c2", "DOC2", access_rank=0, region_in=True, effective_int=20260101
    )
    assert scope.is_chunk_eligible(employee_chunk)

    # Future chunk not eligible for current query
    future_chunk = make_dummy_chunk(
        "c3", "DOC3", access_rank=0, region_in=True, effective_int=20270101
    )
    assert not scope.is_chunk_eligible(future_chunk, allow_upcoming=False)
    assert scope.is_chunk_eligible(future_chunk, allow_upcoming=True)


def test_assert_all_eligible_raises_on_violation() -> None:
    ctx = RequestContext(employee_id="E1001", role="employee", region="IN")
    scope = build_scope(ctx, date(2026, 6, 1))

    valid = make_dummy_chunk("c1", "D1", access_rank=0, region_in=True)
    invalid = make_dummy_chunk("c2", "D2", access_rank=2, region_in=True)  # HR only

    assert_all_eligible([valid], scope)

    import pytest

    with pytest.raises(ScopeViolationError) as exc_info:
        assert_all_eligible([valid, invalid], scope)
    assert "D2" in str(exc_info.value)


def test_reciprocal_rank_fusion() -> None:
    dense = [("c1", 0.9), ("c2", 0.8), ("c3", 0.7)]
    lexical = [("c2", 5.0), ("c4", 4.0), ("c1", 3.0)]

    fused = reciprocal_rank_fusion(dense, lexical, k=60)
    top_cids = [cid for cid, _score in fused]
    # c2 was rank 2 in dense and rank 1 in lexical -> should win or tie top
    assert top_cids[0] in ["c1", "c2"]
    assert "c4" in top_cids


def test_group_by_doc_id_diversity() -> None:
    fused = [
        ("doc1_c1", 0.03),
        ("doc1_c2", 0.02),
        ("doc1_c3", 0.01),
        ("doc2_c1", 0.009),
    ]
    chunk_doc_map = {
        "doc1_c1": "doc1",
        "doc1_c2": "doc1",
        "doc1_c3": "doc1",
        "doc2_c1": "doc2",
    }
    grouped = group_by_doc_id(fused, chunk_doc_map, max_chunks_per_doc=2, limit=5)
    # doc1_c3 should be omitted because max 2 chunks per doc
    assert "doc1_c1" in grouped
    assert "doc1_c2" in grouped
    assert "doc1_c3" not in grouped
    assert "doc2_c1" in grouped


def test_greedy_packer_budget() -> None:
    chunks = [make_dummy_chunk(f"c{i}", f"D{i}", token_count=100) for i in range(10)]
    # Pack into tight budget of 250 tokens
    packed_text, packed_chunks, total_tokens = pack_evidence(chunks, max_budget_tokens=250)
    assert total_tokens <= 250
    assert len(packed_chunks) >= 2
    assert "[DOCUMENT: D0" in packed_text
