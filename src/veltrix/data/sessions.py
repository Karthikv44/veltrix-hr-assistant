"""Session management, conversation history, and pending proposal storage."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from veltrix.domain.models import Role


class SessionOwnershipConflict(Exception):
    """Raised when a session_id is accessed by an employee who does not own it (HTTP 403)."""


@dataclass
class Proposal:
    """Pending write action proposal waiting for confirmation."""

    session_id: str
    employee_id: str
    action_type: str
    payload: dict[str, Any]
    created_at: str


class SessionManager:
    """Manages session binding, ownership verification, and write proposals."""

    def __init__(self, app_db_path: str) -> None:
        self.app_db_path = app_db_path

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.app_db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def bind_and_verify_session(self, session_id: str, employee_id: str) -> None:
        """Atomically bind session to employee_id if new, or verify ownership.

        Raises SessionOwnershipConflict (403) if session exists with a different owner.
        """
        now_iso = datetime.now().isoformat()
        with self._get_conn() as conn:
            with conn:
                # Insert if not exists
                conn.execute(
                    """
                    INSERT OR IGNORE INTO sessions (session_id, employee_id, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (session_id, employee_id, now_iso),
                )
                # Fetch owner
                row = conn.execute(
                    "SELECT employee_id FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()

                if row and row["employee_id"] != employee_id:
                    raise SessionOwnershipConflict(
                        f"Session {session_id} is owned by another employee."
                    )

    def save_proposal(
        self, session_id: str, employee_id: str, action_type: str, payload: dict[str, Any]
    ) -> None:
        """Store or update pending write proposal for the session."""
        now_iso = datetime.now().isoformat()
        with self._get_conn() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO proposals (session_id, employee_id, action_type, payload, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        employee_id = excluded.employee_id,
                        action_type = excluded.action_type,
                        payload = excluded.payload,
                        created_at = excluded.created_at
                    """,
                    (session_id, employee_id, action_type, json.dumps(payload), now_iso),
                )

    def get_proposal(self, session_id: str) -> Proposal | None:
        """Retrieve the pending proposal for a session, if any."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT session_id, employee_id, action_type, payload, created_at FROM proposals WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if not row:
                return None
            return Proposal(
                session_id=row["session_id"],
                employee_id=row["employee_id"],
                action_type=row["action_type"],
                payload=json.loads(row["payload"]),
                created_at=row["created_at"],
            )

    def clear_proposal(self, session_id: str) -> None:
        """Delete pending proposal for the session."""
        with self._get_conn() as conn:
            with conn:
                conn.execute("DELETE FROM proposals WHERE session_id = ?", (session_id,))
