"""ChromaDB implementation of VectorStore using PersistentClient and precomputed embeddings."""

import contextlib
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from veltrix.core.logging import get_logger
from veltrix.ingestion.chunker import Chunk

logger = get_logger("chroma_store")

COLLECTION_NAME = "veltrix_chunks"


class ChromaVectorStore:
    """Embedded ChromaDB vector store running PersistentClient in cosine distance space.

    Enforces:
    - Cosine space: "hnsw:space": "cosine"
    - anonymized_telemetry: False
    - Always passes precomputed embeddings (never triggers downloads)
    - Rebuilds safely
    """

    def __init__(self, persist_dir: Path | str) -> None:
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection = self._get_or_create_collection()

    def _get_or_create_collection(self) -> chromadb.Collection:
        return self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    async def add_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if not chunks:
            return

        ids = [c.chunk_id for c in chunks]
        documents = [c.text for c in chunks]
        metadatas = [c.metadata for c in chunks]

        # Chroma handles up to several thousand in batches
        batch_size = 500
        for i in range(0, len(chunks), batch_size):
            self._collection.upsert(
                ids=ids[i : i + batch_size],
                embeddings=embeddings[i : i + batch_size],  # Precomputed embeddings
                documents=documents[i : i + batch_size],
                metadatas=metadatas[i : i + batch_size],
            )
        logger.info("Indexed chunks into ChromaDB", count=len(chunks))

    async def query(
        self,
        query_embedding: list[float],
        where: dict[str, Any],
        limit: int = 10,
    ) -> list[tuple[str, float]]:
        if self._collection.count() == 0:
            return []

        # If where query is empty, pass None
        where_filter = where if where else None

        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=min(limit, self._collection.count()),
            where=where_filter,
            include=["distances"],
        )

        res_ids = results.get("ids", [[]])[0]
        res_dists = results.get("distances", [[]])[0] if results.get("distances") else []

        # In cosine space, distance = 1 - cosine_similarity. Similarity = 1 - distance.
        items: list[tuple[str, float]] = []
        for cid, dist in zip(res_ids, res_dists, strict=False):
            sim = 1.0 - float(dist)
            items.append((cid, sim))

        return items

    async def reset(self) -> None:
        with contextlib.suppress(Exception):
            self._client.delete_collection(COLLECTION_NAME)
        self._collection = self._get_or_create_collection()
        logger.info("Chroma collection reset successfully")

    async def count(self) -> int:
        return self._collection.count()
