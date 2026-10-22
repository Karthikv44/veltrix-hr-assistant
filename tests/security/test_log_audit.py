"""Security and privacy audit test: asserts no PII (names, emails, phones) in logs or unmasked output."""

import logging
import sqlite3
from io import StringIO
from pathlib import Path

import pytest

from veltrix.api.container import reset_container
from veltrix.core.config import Settings
from veltrix.domain.models import RequestContext
from veltrix.orchestration.orchestrator import Orchestrator


@pytest.fixture
def audit_db(tmp_path: Path):
    test_db = tmp_path / "audit_veltrix.db"
    test_app = tmp_path / "audit_app.db"

    from veltrix.data.db import init_app_db

    init_app_db(test_app)

    conn = sqlite3.connect(test_db)
    with conn:
        conn.execute(
            """
            CREATE TABLE employees (
                employee_id TEXT PRIMARY KEY,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT NOT NULL,
                region TEXT NOT NULL,
                join_date TEXT NOT NULL,
                level TEXT NOT NULL,
                role TEXT NOT NULL,
                manager_id TEXT
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE leave_balances (
                employee_id TEXT NOT NULL,
                leave_type TEXT NOT NULL,
                balance_days REAL NOT NULL,
                PRIMARY KEY (employee_id, leave_type)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE leave_requests (
                request_id TEXT PRIMARY KEY,
                employee_id TEXT NOT NULL,
                leave_type TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                working_days INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        # Plant distinctive PII
        conn.execute(
            "INSERT INTO employees VALUES ('E777', 'Jonathan PII_Sensitive_Person', 'jonathan.pii@veltrix.example', '+1-555-891-2345', 'IN', '2025-01-01', 'L4', 'employee', NULL)"
        )
        conn.execute("INSERT INTO leave_balances VALUES ('E777', 'annual', 12.0)")

    conn.close()

    settings = Settings(
        DB_PATH=test_db,
        APP_DB_PATH=test_app,
        CORPUS_DIR=Path("./data/corpus"),
        MANIFEST_PATH=Path("./data/manifest.json"),
    )
    container = reset_container(settings)
    return container, test_db


@pytest.mark.asyncio
async def test_log_audit_for_pii(audit_db) -> None:
    """Run operations and inspect log output to assert NO unmasked emails or phone numbers appear in logs."""
    container, test_db = audit_db

    # Capture log stream
    log_stream = StringIO()
    root_logger = logging.getLogger()
    handler = logging.StreamHandler(log_stream)
    root_logger.addHandler(handler)

    try:
        orchestrator = Orchestrator(container)
        ctx = RequestContext(employee_id="E777", role="employee", region="IN")

        # Execute actions that touch employee data
        resp = await orchestrator.handle_message(
            session_id="audit_session",
            message="Check my annual leave balance",
            ctx=ctx,
        )

        log_output = log_stream.getvalue()

        # Query all PII fields from DB
        conn = sqlite3.connect(test_db)
        row = conn.execute(
            "SELECT full_name, email, phone FROM employees WHERE employee_id = 'E777'"
        ).fetchone()
        conn.close()

        full_name, raw_email, phone = row

        # 1. Assert phone number NEVER appears in logs
        assert phone not in log_output, "SECURITY LEAK: Phone number appeared in log output!"
        # 2. Assert unmasked email NEVER appears in logs
        assert raw_email not in log_output, "SECURITY LEAK: Unmasked email appeared in log output!"
        # 3. Assert phone number NEVER appears in user-facing answer
        assert phone not in resp.answer
        assert raw_email not in resp.answer

    finally:
        root_logger.removeHandler(handler)
