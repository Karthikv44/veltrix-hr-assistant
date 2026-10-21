"""Complete document ingestion pipeline orchestrating loading, cleaning, chunking, holiday extraction, and indexing."""

import sqlite3
from dataclasses import dataclass

from veltrix.core.config import Settings
from veltrix.core.logging import get_logger
from veltrix.data.db import init_app_db
from veltrix.ingestion.chunker import Chunk, DocumentChunker
from veltrix.ingestion.cleaning import clean_document_elements
from veltrix.ingestion.holidays import extract_and_store_holidays
from veltrix.ingestion.loaders.registry import loader_registry
from veltrix.ingestion.manifest import ManifestLoader
from veltrix.retrieval.chroma_store import ChromaVectorStore
from veltrix.retrieval.embedder import Embedder, FastEmbedEmbedder

logger = get_logger("pipeline")


@dataclass
class IngestionResult:
    """Statistics summarizing ingestion execution."""

    documents_indexed: int
    chunks_created: int
    holidays_extracted: int
    skipped: bool
    corpus_hash: str


class IngestionPipeline:
    """Pipeline orchestrating end-to-end ingestion into ChromaDB and SQLite app.db."""

    def __init__(
        self,
        settings: Settings,
        embedder: Embedder | None = None,
        vector_store: ChromaVectorStore | None = None,
    ) -> None:
        self.settings = settings
        self.manifest_loader = ManifestLoader(settings.MANIFEST_PATH, settings.CORPUS_DIR)
        self.chunker = DocumentChunker()
        self.embedder = embedder or FastEmbedEmbedder(model_name=settings.FAST_EMBED_MODEL)
        self.vector_store = vector_store or ChromaVectorStore(settings.CHROMA_DIR)

    def _get_stored_hash(self) -> str | None:
        """Fetch previously stored corpus hash from SQLite app.db."""
        conn = sqlite3.connect(self.settings.APP_DB_PATH)
        try:
            row = conn.execute(
                "SELECT value FROM ingestion_meta WHERE key = 'corpus_hash'"
            ).fetchone()
            return row[0] if row else None
        except sqlite3.OperationalError:
            return None
        finally:
            conn.close()

    def _save_stored_hash(self, corpus_hash: str) -> None:
        """Save new corpus hash into SQLite app.db."""
        conn = sqlite3.connect(self.settings.APP_DB_PATH)
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO ingestion_meta (key, value, updated_at)
                    VALUES ('corpus_hash', ?, datetime('now'))
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = excluded.updated_at
                    """,
                    (corpus_hash,),
                )
        finally:
            conn.close()

    def _store_chunks_in_sqlite(self, chunks: list[Chunk]) -> None:
        """Store chunk records in SQLite app.db for BM25 and scope-based retrieval."""
        conn = sqlite3.connect(self.settings.APP_DB_PATH)
        try:
            with conn:
                for c in chunks:
                    m = c.metadata
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO chunks (
                            chunk_id, doc_id, doc_type, title, text, embedded_text, locator,
                            token_count, authority_rank, access_rank, effective_int, effective_date,
                            region_GLOBAL, region_IN, region_US, region_DE
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            c.chunk_id,
                            c.doc_id,
                            m.get("doc_type", ""),
                            m.get("title", ""),
                            c.text,
                            c.embedded_text,
                            c.locator,
                            c.token_count,
                            m.get("authority_rank", 1),
                            m.get("access_rank", 0),
                            m.get("effective_int", 0),
                            m.get("effective_date", ""),
                            bool(m.get("region_GLOBAL", False)),
                            bool(m.get("region_IN", False)),
                            bool(m.get("region_US", False)),
                            bool(m.get("region_DE", False)),
                        ),
                    )
        finally:
            conn.close()

    async def run(self, force_rebuild: bool = False) -> IngestionResult:
        """Run the ingestion pipeline.

        Idempotent: skips if corpus+manifest hash matches stored hash and vector store is non-empty.
        """
        init_app_db(self.settings.APP_DB_PATH)

        manifest_items = self.manifest_loader.load()
        corpus_hash = self.manifest_loader.compute_corpus_hash()
        stored_hash = self._get_stored_hash()
        vector_count = await self.vector_store.count()

        if not force_rebuild and stored_hash == corpus_hash and vector_count > 0:
            logger.info(
                "Corpus hash unchanged and vector store populated. Skipping ingestion.",
                hash=corpus_hash,
            )
            return IngestionResult(
                documents_indexed=len(manifest_items),
                chunks_created=vector_count,
                holidays_extracted=0,
                skipped=True,
                corpus_hash=corpus_hash,
            )

        logger.info(
            "Starting corpus ingestion and indexing...", count=len(manifest_items), hash=corpus_hash
        )

        # Reset collections and tables for fresh build
        await self.vector_store.reset()
        conn = sqlite3.connect(self.settings.APP_DB_PATH)
        with conn:
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM holidays")
        conn.close()

        all_known_regions: set[str] = {"GLOBAL"}
        for it in manifest_items:
            all_known_regions.update(it.regions)

        all_chunks: list[Chunk] = []
        total_holidays = 0
        docs_indexed = 0

        for item in manifest_items:
            file_path = self.settings.CORPUS_DIR / item.file
            if not file_path.exists():
                logger.warning("Corpus file does not exist", file=item.file, doc_id=item.doc_id)
                continue

            try:
                # 1. Load document via registered loader
                loader = loader_registry.get(file_path)
                raw_doc = loader.load(file_path, item)

                # 2. Clean elements (strip in-doc metadata tables and repeated headers/footers)
                total_pages = max([el.page_num for el in raw_doc.elements], default=1)
                cleaned_elements = clean_document_elements(raw_doc.elements, item, total_pages)

                # 3. Extract holidays if calendar document
                if item.doc_type == "calendar":
                    hols = extract_and_store_holidays(
                        raw_doc.elements, item, str(self.settings.APP_DB_PATH)
                    )
                    total_holidays += len(hols)

                # 4. Chunk elements
                doc_chunks = self.chunker.chunk_document(cleaned_elements, item, all_known_regions)
                all_chunks.extend(doc_chunks)
                docs_indexed += 1

            except Exception as e:
                logger.error(
                    "Failed to ingest document, continuing with others",
                    doc_id=item.doc_id,
                    file=item.file,
                    error=str(e),
                )
                continue

        if not all_chunks:
            logger.error("Ingestion produced 0 chunks. Service will not be ready.")
            return IngestionResult(
                documents_indexed=0,
                chunks_created=0,
                holidays_extracted=0,
                skipped=False,
                corpus_hash=corpus_hash,
            )

        # 5. Embed all chunks using FastEmbed
        logger.info("Generating embeddings for chunks...", count=len(all_chunks))
        texts_to_embed = [c.embedded_text for c in all_chunks]
        embeddings = self.embedder.embed_texts(texts_to_embed)

        # 6. Index into Chroma and SQLite app.db
        await self.vector_store.add_chunks(all_chunks, embeddings)
        self._store_chunks_in_sqlite(all_chunks)

        # 7. Record hash for idempotency
        self._save_stored_hash(corpus_hash)

        logger.info(
            "Ingestion completed successfully",
            documents_indexed=docs_indexed,
            chunks_created=len(all_chunks),
            holidays_extracted=total_holidays,
        )

        return IngestionResult(
            documents_indexed=docs_indexed,
            chunks_created=len(all_chunks),
            holidays_extracted=total_holidays,
            skipped=False,
            corpus_hash=corpus_hash,
        )
