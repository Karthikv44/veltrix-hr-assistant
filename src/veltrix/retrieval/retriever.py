"""Unified hybrid retriever combining dense vector search, BM25, and RRF under strict scope."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from veltrix.core.logging import get_logger
from veltrix.ingestion.chunker import Chunk
from veltrix.retrieval.chroma_store import ChromaVectorStore
from veltrix.retrieval.embedder import Embedder
from veltrix.retrieval.fusion import group_by_doc_id, reciprocal_rank_fusion
from veltrix.retrieval.lexical import LexicalRetriever
from veltrix.retrieval.packer import pack_evidence
from veltrix.retrieval.scope import RetrievalScope, assert_all_eligible

logger = get_logger("retriever")


@dataclass
class RetrievalResult:
    """Complete structured output from hybrid retrieval."""

    packed_evidence: str
    chunks: list[Chunk]
    upcoming_chunks: list[Chunk]
    total_tokens: int


class HybridRetriever:
    """Retriever requiring a RetrievalScope for every query.

    Enforces:
    - Search without a scope is impossible by signature.
    - Pre-filter in Chroma dense search (access_rank, regions, effective date).
    - BM25 scored strictly over eligible chunk IDs from the same scope.
    - Fused with Reciprocal Rank Fusion (RRF).
    - Grouped by doc_id (top 2 chunks per doc).
    - Greedily packed up to 2,800 tokens.
    - assert_all_eligible called before returning chunks.
    """

    def __init__(
        self,
        vector_store: ChromaVectorStore,
        embedder: Embedder,
        app_db_path: Path | str,
    ) -> None:
        self.vector_store = vector_store
        self.embedder = embedder
        self.app_db_path = str(app_db_path)
        self.lexical = LexicalRetriever(self.app_db_path)

    def _load_chunks_by_ids(self, chunk_ids: list[str]) -> list[Chunk]:
        """Fetch Chunk domain models from SQLite app.db by chunk_id."""
        if not chunk_ids:
            return []

        conn = sqlite3.connect(self.app_db_path)
        conn.row_factory = sqlite3.Row
        try:
            placeholders = ",".join("?" for _ in chunk_ids)
            query = f"SELECT * FROM chunks WHERE chunk_id IN ({placeholders})"
            rows = conn.execute(query, tuple(chunk_ids)).fetchall()
            row_map = {r["chunk_id"]: r for r in rows}

            chunks: list[Chunk] = []
            for cid in chunk_ids:
                r = row_map.get(cid)
                if not r:
                    continue
                meta = {
                    "doc_id": r["doc_id"],
                    "doc_type": r["doc_type"],
                    "title": r["title"],
                    "locator": r["locator"],
                    "token_count": r["token_count"],
                    "authority_rank": r["authority_rank"],
                    "access_rank": r["access_rank"],
                    "effective_int": r["effective_int"],
                    "effective_date": r["effective_date"],
                    "region_GLOBAL": bool(r["region_GLOBAL"]),
                    "region_IN": bool(r["region_IN"]),
                    "region_US": bool(r["region_US"]),
                    "region_DE": bool(r["region_DE"]),
                }
                chunks.append(
                    Chunk(
                        chunk_id=r["chunk_id"],
                        doc_id=r["doc_id"],
                        text=r["text"],
                        embedded_text=r["embedded_text"],
                        locator=r["locator"],
                        token_count=r["token_count"],
                        metadata=meta,
                    )
                )
            return chunks
        finally:
            conn.close()

    def _get_chunk_doc_map(self) -> dict[str, str]:
        """Fetch mapping from chunk_id to doc_id from SQLite app.db."""
        conn = sqlite3.connect(self.app_db_path)
        try:
            rows = conn.execute("SELECT chunk_id, doc_id FROM chunks").fetchall()
            return {r[0]: r[1] for r in rows}
        finally:
            conn.close()

    async def retrieve(
        self,
        query: str,
        scope: RetrievalScope,
        dense_limit: int = 25,
        lexical_limit: int = 25,
        final_limit: int = 15,
    ) -> RetrievalResult:
        """Perform hybrid retrieval strictly under the provided RetrievalScope."""
        # 1. Embed query
        query_embedding = self.embedder.embed_texts([query])[0]

        # 2. Dense search with pre-filters for current policies
        where_current = scope.to_chroma_where(upcoming=False)
        dense_current = await self.vector_store.query(
            query_embedding=query_embedding,
            where=where_current,
            limit=dense_limit,
        )

        # 3. BM25 search over eligible chunks only
        lexical_current = self.lexical.search(
            query_text=query,
            scope=scope,
            limit=lexical_limit,
            upcoming=False,
        )

        # 4. Fuse current results via RRF
        fused_current = reciprocal_rank_fusion(dense_current, lexical_current, k=60)

        # 5. Group by doc_id (max 2 chunks per doc) to preserve competing versions
        chunk_doc_map = self._get_chunk_doc_map()
        selected_ids = group_by_doc_id(
            fused_current, chunk_doc_map, max_chunks_per_doc=2, limit=final_limit
        )
        current_chunks = self._load_chunks_by_ids(selected_ids)

        # 6. Defense-in-depth security assertion
        assert_all_eligible(current_chunks, scope, allow_upcoming=False)

        # 7. Check for upcoming changes (effective_int > ref_int)
        where_upcoming = scope.to_chroma_where(upcoming=True)
        dense_upcoming = await self.vector_store.query(
            query_embedding=query_embedding,
            where=where_upcoming,
            limit=10,
        )
        lexical_upcoming = self.lexical.search(
            query_text=query,
            scope=scope,
            limit=10,
            upcoming=True,
        )
        fused_upcoming = reciprocal_rank_fusion(dense_upcoming, lexical_upcoming, k=60)
        upcoming_ids = group_by_doc_id(fused_upcoming, chunk_doc_map, max_chunks_per_doc=2, limit=5)
        upcoming_chunks = self._load_chunks_by_ids(upcoming_ids)
        assert_all_eligible(upcoming_chunks, scope, allow_upcoming=True)

        # 8. Pack evidence greedily up to 2,800 tokens
        packed_text, packed_chunks, total_tokens = pack_evidence(
            current_chunks, max_budget_tokens=2800
        )

        return RetrievalResult(
            packed_evidence=packed_text,
            chunks=packed_chunks,
            upcoming_chunks=upcoming_chunks,
            total_tokens=total_tokens,
        )
