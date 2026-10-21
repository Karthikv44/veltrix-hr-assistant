"""In-process BM25 lexical retriever scoring strictly over eligible chunk sets."""

import re
import sqlite3

from rank_bm25 import BM25Okapi

from veltrix.core.logging import get_logger
from veltrix.retrieval.scope import RetrievalScope

logger = get_logger("lexical")


def tokenize_query_or_doc(text: str) -> list[str]:
    """Tokenize text into lowercase alphanumeric terms for BM25."""
    return re.findall(r"\b[a-zA-Z0-9_-]+\b", text.lower())


class LexicalRetriever:
    """In-process BM25 lexical search scored ONLY over eligible chunk-id set."""

    def __init__(self, app_db_path: str) -> None:
        self.app_db_path = app_db_path

    def get_eligible_chunk_ids(self, scope: RetrievalScope, upcoming: bool = False) -> set[str]:
        """Query SQLite app.db chunks table to determine the exact set of eligible chunk IDs."""
        date_op = ">" if upcoming else "<="
        region_col = f"region_{scope.region.upper()}"

        query = f"""
            SELECT chunk_id
            FROM chunks
            WHERE access_rank <= ?
              AND (region_GLOBAL = 1 OR {region_col} = 1)
              AND effective_int {date_op} ?
        """

        conn = sqlite3.connect(self.app_db_path)
        try:
            rows = conn.execute(query, (scope.role_rank, scope.ref_int)).fetchall()
            return {r[0] for r in rows}
        finally:
            conn.close()

    def search(
        self,
        query_text: str,
        scope: RetrievalScope,
        limit: int = 15,
        upcoming: bool = False,
    ) -> list[tuple[str, float]]:
        """Score eligible chunks using BM25. Ineligible chunks are never scored or returned."""
        eligible_ids = self.get_eligible_chunk_ids(scope, upcoming=upcoming)
        if not eligible_ids:
            return []

        # Fetch chunk texts for eligible IDs only
        conn = sqlite3.connect(self.app_db_path)
        try:
            placeholders = ",".join("?" for _ in eligible_ids)
            query = f"SELECT chunk_id, embedded_text FROM chunks WHERE chunk_id IN ({placeholders})"
            rows = conn.execute(query, tuple(eligible_ids)).fetchall()
        finally:
            conn.close()

        if not rows:
            return []

        chunk_ids = [r[0] for r in rows]
        corpus = [tokenize_query_or_doc(r[1]) for r in rows]

        tokenized_query = tokenize_query_or_doc(query_text)
        if not tokenized_query:
            return []

        bm25 = BM25Okapi(corpus)
        scores = bm25.get_scores(tokenized_query)

        scored_pairs: list[tuple[str, float]] = []
        for cid, score in zip(chunk_ids, scores, strict=False):
            if score > 0.0:
                scored_pairs.append((cid, float(score)))

        # Sort descending by BM25 score, deterministic tie-break on chunk_id
        scored_pairs.sort(key=lambda x: (x[1], x[0]), reverse=True)
        return scored_pairs[:limit]
