"""Integration test verifying full ingestion against the real corpus in data/."""

import sqlite3
from pathlib import Path

import pytest

from veltrix.core.config import Settings
from veltrix.ingestion.pipeline import IngestionPipeline
from veltrix.retrieval.chroma_store import ChromaVectorStore
from veltrix.retrieval.embedder import FakeEmbedder


@pytest.mark.asyncio
async def test_full_ingestion_real_corpus(tmp_path: Path) -> None:
    """Test complete pipeline execution with all 30 real documents in data/corpus."""
    test_app_db = tmp_path / "test_app.db"
    test_chroma = tmp_path / "test_chroma"

    settings = Settings(
        CORPUS_DIR=Path("./data/corpus"),
        MANIFEST_PATH=Path("./data/manifest.json"),
        APP_DB_PATH=test_app_db,
        CHROMA_DIR=test_chroma,
    )

    # Use FakeEmbedder for rapid and deterministic test execution
    embedder = FakeEmbedder(dimension=384)
    vector_store = ChromaVectorStore(persist_dir=test_chroma)
    pipeline = IngestionPipeline(settings=settings, embedder=embedder, vector_store=vector_store)

    # Run ingestion
    res = await pipeline.run(force_rebuild=True)
    assert res.documents_indexed == 30
    assert res.chunks_created > 50
    assert res.holidays_extracted > 0
    assert res.skipped is False

    # Check SQLite chunks table
    conn = sqlite3.connect(test_app_db)
    chunk_count = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
    holiday_count = conn.execute("SELECT count(*) FROM holidays").fetchone()[0]
    conn.close()

    assert chunk_count == res.chunks_created
    assert holiday_count == res.holidays_extracted

    # Test idempotency (second run skips without rebuilding)
    res_second = await pipeline.run(force_rebuild=False)
    assert res_second.skipped is True
    assert res_second.chunks_created == res.chunks_created
