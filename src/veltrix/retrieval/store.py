"""Vector store abstract interface."""

from typing import Any, Protocol

from veltrix.ingestion.chunker import Chunk


class VectorStore(Protocol):
    """Vector store interface supporting dense query with scalar metadata pre-filtering."""

    async def add_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        """Add chunks and precomputed embeddings to the vector store."""
        ...

    async def query(
        self,
        query_embedding: list[float],
        where: dict[str, Any],
        limit: int = 10,
    ) -> list[tuple[str, float]]:
        """Query vector store using dense vector and scalar metadata pre-filters.

        Returns:
            List of (chunk_id, distance_or_score).
        """
        ...

    async def reset(self) -> None:
        """Reset or clear all stored vectors and documents."""
        ...

    async def count(self) -> int:
        """Return total number of vectors in the store."""
        ...
