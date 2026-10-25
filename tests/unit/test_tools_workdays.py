"""Unit and integration tests for tools, workdays, date parsing, permissions, and 2-step confirmations."""

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from veltrix.data.db import init_app_db
from veltrix.data.sessions import SessionManager
from veltrix.domain.dates import resolve_date_phrase
from veltrix.domain.models import RequestContext
from veltrix.orchestration.pipelines.tool import ToolPipeline
from veltrix.tools.leave import LeaveTools
from veltrix.tools.permissions import can_manage_team_leave, can_view_employee_leave


@pytest.fixture
def test_tools_env(tmp_path: Path):
    test_veltrix_db = tmp_path / "veltrix_test.db"
    test_app_db = tmp_path / "app_test.db"

    init_app_db(test_app_db)

    # Populate temporary veltrix.db
    conn = sqlite3.connect(test_veltrix_db)
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

        # Seed test employees: E1001 (emp), M2001 (mgr of E1001), H3001 (hr), O9999 (other)
        conn.execute(
            "INSERT INTO employees VALUES ('E1001', 'Alice Employee', 'alice@veltrix.example', '1234567890', 'IN', '2025-01-01', 'L3', 'employee', 'M2001')"
        )
        conn.execute(
            "INSERT INTO employees VALUES ('M2001', 'Bob Manager', 'bob@veltrix.example', '1234567891', 'IN', '2024-01-01', 'L5', 'manager', NULL)"
        )
        conn.execute(
            "INSERT INTO employees VALUES ('H3001', 'Helen HR', 'helen@veltrix.example', '1234567892', 'IN', '2023-01-01', 'L5', 'hr', NULL)"
        )
        conn.execute(
            "INSERT INTO employees VALUES ('O9999', 'Other Person', 'other@veltrix.example', '1234567893', 'IN', '2025-01-01', 'L2', 'employee', 'M8888')"
        )

        # Seed balances
        conn.execute("INSERT INTO leave_balances VALUES ('E1001', 'annual', 15.0)")
        conn.execute("INSERT INTO leave_balances VALUES ('E1001', 'sick', 10.0)")

    conn.close()

    tools = LeaveTools(db_path=str(test_veltrix_db), app_db_path=str(test_app_db))
    session_mgr = SessionManager(str(test_app_db))
    pipeline = ToolPipeline(leave_tools=tools, session_manager=session_mgr)

    return tools, pipeline, test_veltrix_db, test_app_db


def test_date_phrase_resolution() -> None:
    today = date(2026, 9, 15)  # Tuesday
    assert resolve_date_phrase("today", today) == today
    assert resolve_date_phrase("tomorrow", today) == date(2026, 9, 16)

    # Next Friday (first Friday after Tuesday Sep 15 is Friday Sep 18)
    assert resolve_date_phrase("next Friday", today) == date(2026, 9, 18)

    # Next week (Monday Sep 21 to Friday Sep 25)
    mon, fri = resolve_date_phrase("next week", today)
    assert mon == date(2026, 9, 21)
    assert fri == date(2026, 9, 25)


def test_leave_permissions_matrix() -> None:
    emp = RequestContext(employee_id="E1001", role="employee", region="IN")
    mgr = RequestContext(employee_id="M2001", role="manager", region="IN")
    hr = RequestContext(employee_id="H3001", role="hr", region="IN")

    direct_reports = {"E1001"}

    # Employee can only see self
    assert can_view_employee_leave(emp, "E1001", direct_report_ids=set())
    assert not can_view_employee_leave(emp, "O9999", direct_report_ids=set())

    # Manager can see self and direct reports
    assert can_view_employee_leave(mgr, "M2001", direct_report_ids=direct_reports)
    assert can_view_employee_leave(mgr, "E1001", direct_report_ids=direct_reports)
    assert not can_view_employee_leave(mgr, "O9999", direct_report_ids=direct_reports)

    # HR can see any one employee
    assert can_view_employee_leave(hr, "E1001", direct_report_ids=set())
    assert can_view_employee_leave(hr, "O9999", direct_report_ids=set())

    # get_team_leave is manager only
    assert can_manage_team_leave(mgr)
    assert not can_manage_team_leave(emp)
    assert not can_manage_team_leave(hr)


@pytest.mark.asyncio
async def test_apply_and_cancel_two_step_confirmation(test_tools_env) -> None:
    tools, pipeline, veltrix_db, app_db = test_tools_env
    ctx = RequestContext(employee_id="E1001", role="employee", region="IN")
    today = date(2026, 9, 15)
    session_id = "test_sess_confirm"

    # Step 1: Propose apply_leave
    msg1 = "apply for annual leave from 2026-10-05 to 2026-10-09"
    resp1 = await pipeline.execute_or_propose(session_id, msg1, ctx, today)
    assert resp1.route == "tool"
    assert resp1.pending_confirmation is True
    assert len(resp1.tool_calls) == 1
    assert resp1.tool_calls[0].status == "pending_confirmation"
    assert "confirm" in resp1.answer.lower()

    # Verify nothing changed in database yet
    conn = sqlite3.connect(veltrix_db)
    req_count = conn.execute("SELECT count(*) FROM leave_requests").fetchone()[0]
    bal = conn.execute(
        "SELECT balance_days FROM leave_balances WHERE employee_id = 'E1001' AND leave_type = 'annual'"
    ).fetchone()[0]
    conn.close()
    assert req_count == 0
    assert bal == 15.0

    # Step 2: Clear confirmation ("yes")
    resp2 = await pipeline.execute_or_propose(session_id, "yes", ctx, today)
    assert resp2.route == "tool"
    assert resp2.pending_confirmation is False
    assert len(resp2.tool_calls) == 1
    assert resp2.tool_calls[0].status == "success"
    assert "submitted successfully" in resp2.answer

    # Verify atomic transaction updated DB
    conn = sqlite3.connect(veltrix_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM leave_requests WHERE employee_id = 'E1001'").fetchone()
    new_bal = conn.execute(
        "SELECT balance_days FROM leave_balances WHERE employee_id = 'E1001' AND leave_type = 'annual'"
    ).fetchone()[0]
    conn.close()
    assert row is not None
    assert row["status"] == "pending"
    assert row["working_days"] == 5
    assert new_bal == 10.0

    created_request_id = row["request_id"]

    # Step 3: Propose cancel_leave
    msg3 = f"cancel leave {created_request_id}"
    resp3 = await pipeline.execute_or_propose(session_id, msg3, ctx, today)
    assert resp3.route == "tool"
    assert resp3.pending_confirmation is True
    assert resp3.tool_calls[0].status == "pending_confirmation"

    # Step 4: Confirm cancellation ("go ahead")
    resp4 = await pipeline.execute_or_propose(session_id, "go ahead", ctx, today)
    assert resp4.route == "tool"
    assert resp4.pending_confirmation is False
    assert resp4.tool_calls[0].status == "success"

    # Verify refund in DB
    conn = sqlite3.connect(veltrix_db)
    cancel_row = conn.execute(
        "SELECT status FROM leave_requests WHERE request_id = ?", (created_request_id,)
    ).fetchone()
    refunded_bal = conn.execute(
        "SELECT balance_days FROM leave_balances WHERE employee_id = 'E1001' AND leave_type = 'annual'"
    ).fetchone()[0]
    conn.close()
    assert cancel_row[0] == "cancelled"
    assert refunded_bal == 15.0


@pytest.mark.asyncio
async def test_apply_leave_validation_rejections(test_tools_env) -> None:
    tools, pipeline, veltrix_db, app_db = test_tools_env
    ctx = RequestContext(employee_id="E1001", role="employee", region="IN")
    today = date(2026, 9, 15)
    session_id = "test_sess_reject"

    # 1. Past start date
    msg = "apply for annual leave from 2026-08-01 to 2026-08-05"
    resp = await pipeline.execute_or_propose(session_id, msg, ctx, today)
    assert resp.route == "tool"
    assert resp.tool_calls[0].status == "error"
    assert "past" in resp.answer.lower()
    assert resp.pending_confirmation is False

    # 2. Outside 2026
    msg_2027 = "apply for annual leave from 2027-01-05 to 2027-01-10"
    resp_2027 = await pipeline.execute_or_propose(session_id, msg_2027, ctx, today)
    assert resp_2027.route == "tool"
    assert resp_2027.tool_calls[0].status == "error"
    assert "2026" in resp_2027.answer


@pytest.mark.asyncio
async def test_pending_proposal_unrelated_input_does_not_default_to_balance(
    test_tools_env,
) -> None:
    tools, pipeline, veltrix_db, app_db = test_tools_env
    ctx = RequestContext(employee_id="E1001", role="employee", region="IN")
    today = date(2026, 9, 15)
    session_id = "test_sess_unrelated"

    # Step 1: Propose apply_leave
    msg1 = "apply for annual leave from 2026-10-05 to 2026-10-09"
    resp1 = await pipeline.execute_or_propose(session_id, msg1, ctx, today)
    assert resp1.pending_confirmation is True

    # Step 2: User inputs random text "Something"
    resp2 = await pipeline.execute_or_propose(session_id, "Something", ctx, today)
    assert resp2.pending_confirmation is False
    # Must NOT execute get_leave_balance or return leave balance
    assert "remaining leave balance" not in resp2.answer.lower()
    assert not any(tc.name == "get_leave_balance" for tc in resp2.tool_calls)
