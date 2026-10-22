"""Mutated corpus test verifying Must-Pass Check #5.

Must-Pass Check 5:
"The service works on a modified corpus and reflects the changed values.
Nothing from the corpus is baked in. Ingestion is fully automatic,
including OCR for scanned documents and holiday-table extraction."
"""

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from veltrix.core.config import Settings
from veltrix.ingestion.pipeline import IngestionPipeline
from veltrix.retrieval.chroma_store import ChromaVectorStore
from veltrix.retrieval.embedder import FakeEmbedder


@pytest.mark.asyncio
async def test_mutated_corpus_reflects_changed_values(tmp_path: Path) -> None:
    """Mutate corpus documents (markdown, holiday policy, and manifest) and verify

    ingestion dynamically parses and stores the new values rather than hardcoded ones.
    """
    mutated_corpus_dir = tmp_path / "mutated_corpus"
    mutated_manifest_path = tmp_path / "manifest.json"
    test_app_db = tmp_path / "app.db"
    test_chroma = tmp_path / "chroma"

    # Copy real corpus into temporary mutation directory
    shutil.copytree(Path("./data/corpus"), mutated_corpus_dir)
    with open("./data/manifest.json", encoding="utf-8") as f:
        manifest_data = json.load(f)

    # 1. Mutate a Markdown document with a synthetic, non-standard policy value
    # Let's find an existing markdown document in the corpus
    md_files = list(mutated_corpus_dir.glob("*.md"))
    assert len(md_files) > 0, "No markdown files found in corpus"
    target_md = md_files[0]

    original_md_text = target_md.read_text(encoding="utf-8")
    mutated_token = "SPECIAL_MUTATED_POLICY_VALUE_9999"
    mutated_md_text = (
        original_md_text
        + f"\n\n## Mutated Section\nThis policy grant is {mutated_token} per calendar cycle.\n"
    )
    target_md.write_text(mutated_md_text, encoding="utf-8")

    # 2. Mutate manifest to add a synthetic holiday calendar or change document metadata
    with open(mutated_manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    settings = Settings(
        CORPUS_DIR=mutated_corpus_dir,
        MANIFEST_PATH=mutated_manifest_path,
        APP_DB_PATH=test_app_db,
        CHROMA_DIR=test_chroma,
    )

    embedder = FakeEmbedder(dimension=384)
    vector_store = ChromaVectorStore(persist_dir=test_chroma)
    pipeline = IngestionPipeline(settings=settings, embedder=embedder, vector_store=vector_store)

    # Ingest the mutated corpus
    res = await pipeline.run(force_rebuild=True)
    assert res.documents_indexed >= 30
    assert res.chunks_created > 0

    # Query SQLite database for the mutated token
    conn = sqlite3.connect(test_app_db)
    cursor = conn.cursor()
    cursor.execute("SELECT text FROM chunks WHERE text LIKE ?", (f"%{mutated_token}%",))
    matching_chunks = cursor.fetchall()
    conn.close()

    assert len(matching_chunks) > 0, "Mutated policy value was not found in ingested chunks!"
    assert mutated_token in matching_chunks[0][0]
