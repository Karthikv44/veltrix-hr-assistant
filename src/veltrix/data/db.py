"""SQLite database connection management and schema initialization."""

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path


def get_sqlite_connection(db_path: Path | str, timeout: float = 30.0) -> sqlite3.Connection:
    """Create a configured SQLite connection with foreign keys and Row factory."""
    conn = sqlite3.connect(str(db_path), timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def get_db_cursor(conn: sqlite3.Connection) -> Generator[sqlite3.Cursor, None, None]:
    """Context manager for obtaining a database cursor."""
    cursor = conn.cursor()
    try:
        yield cursor
    finally:
        cursor.close()


def init_app_db(app_db_path: Path | str) -> None:
    """Initialize application database schema in app.db.

    Stores sessions, write proposals, ingested holidays, and chunk metadata.
    Does not touch veltrix.db.
    """
    conn = get_sqlite_connection(app_db_path)
    try:
        with conn:
            # Session ownership binding
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    employee_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

            # Pending write proposals for the two-step confirmation state machine
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS proposals (
                    session_id TEXT PRIMARY KEY,
                    employee_id TEXT NOT NULL,
                    action_type TEXT NOT NULL, -- 'apply_leave' | 'cancel_leave'
                    payload TEXT NOT NULL,     -- JSON payload
                    created_at TEXT NOT NULL
                );
                """
            )

            # Extracted holidays from calendar documents
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS holidays (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id TEXT NOT NULL,
                    date TEXT NOT NULL,        -- 'YYYY-MM-DD'
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,        -- 'public' | 'optional'
                    region TEXT NOT NULL       -- 'IN' | 'US' | 'DE' | 'GLOBAL'
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_holidays_region_date ON holidays (region, date);"
            )

            # Chunks metadata and full text in app.db for BM25 and exact lookup
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    doc_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    text TEXT NOT NULL,
                    embedded_text TEXT NOT NULL,
                    locator TEXT NOT NULL,
                    token_count INTEGER NOT NULL,
                    authority_rank INTEGER NOT NULL,
                    access_rank INTEGER NOT NULL,
                    effective_int INTEGER NOT NULL,
                    effective_date TEXT NOT NULL,
                    region_GLOBAL BOOLEAN NOT NULL,
                    region_IN BOOLEAN NOT NULL,
                    region_US BOOLEAN NOT NULL,
                    region_DE BOOLEAN NOT NULL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks (doc_id);")

            # Ingestion tracking (hash of corpus + manifest)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
    finally:
        conn.close()
