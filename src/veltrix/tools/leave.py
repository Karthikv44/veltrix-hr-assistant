"""Implementation of the 5 leave tools with atomic SQLite BEGIN IMMEDIATE transactions."""

import sqlite3
import uuid
from datetime import date
from typing import Any

from veltrix.api.errors import handle_tool_exceptions
from veltrix.core.logging import get_logger
from veltrix.domain.models import RequestContext
from veltrix.domain.workdays import WorkdayCalculator
from veltrix.tools.permissions import (
    FORBIDDEN_EMPLOYEE_MESSAGE,
    can_manage_team_leave,
    can_view_employee_leave,
)

logger = get_logger("leave_tools")


class LeaveTools:
    """Implements the five exact leave tools specified in TASK.pdf Section 6.1.

    Exact tool names and arguments:
    1. get_leave_balance(employee_id, leave_type?)
    2. list_leave_requests(employee_id, status?)
    3. get_team_leave(start_date, end_date)
    4. apply_leave(leave_type, start_date, end_date)
    5. cancel_leave(request_id)
    """

    def __init__(self, db_path: str, app_db_path: str) -> None:
        self.db_path = str(db_path)
        self.app_db_path = str(app_db_path)
        self.workday_calc = WorkdayCalculator(self.app_db_path)

    def _get_direct_report_ids(self, manager_id: str) -> set[str]:
        """Fetch IDs of all direct reports whose manager_id matches."""
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT employee_id FROM employees WHERE manager_id = ?",
                (manager_id.strip(),),
            ).fetchall()
            return {r[0] for r in rows}
        finally:
            conn.close()

    @handle_tool_exceptions("get_leave_balance")
    async def get_leave_balance(
        self,
        ctx: RequestContext,
        employee_id: str,
        leave_type: str | None = None,
    ) -> dict[str, Any]:
        """Returns the remaining balance of one employee."""
        target_id = employee_id.strip() if employee_id else ctx.employee_id
        reports = self._get_direct_report_ids(ctx.employee_id)

        # Permission check
        if not can_view_employee_leave(ctx, target_id, reports):
            return {"status": "error", "error_message": FORBIDDEN_EMPLOYEE_MESSAGE}

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            query = "SELECT leave_type, balance_days FROM leave_balances WHERE employee_id = ?"
            params: list[Any] = [target_id]
            if leave_type:
                query += " AND leave_type = ?"
                params.append(leave_type.strip().lower())

            rows = conn.execute(query, tuple(params)).fetchall()
            balances = {r["leave_type"]: float(r["balance_days"]) for r in rows}
            return {
                "status": "success",
                "employee_id": target_id,
                "balances": balances,
            }
        finally:
            conn.close()

    @handle_tool_exceptions("list_leave_requests")
    async def list_leave_requests(
        self,
        ctx: RequestContext,
        employee_id: str,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Returns the leave requests of one employee."""
        target_id = employee_id.strip() if employee_id else ctx.employee_id
        reports = self._get_direct_report_ids(ctx.employee_id)

        if not can_view_employee_leave(ctx, target_id, reports):
            return {"status": "error", "error_message": FORBIDDEN_EMPLOYEE_MESSAGE}

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            query = """
                SELECT request_id, employee_id, leave_type, start_date, end_date, working_days, status, created_at
                FROM leave_requests
                WHERE employee_id = ?
            """
            params: list[Any] = [target_id]
            if status:
                query += " AND status = ?"
                params.append(status.strip().lower())
            query += " ORDER BY start_date DESC"

            rows = conn.execute(query, tuple(params)).fetchall()
            requests_list = [dict(r) for r in rows]
            return {
                "status": "success",
                "employee_id": target_id,
                "requests": requests_list,
            }
        finally:
            conn.close()

    @handle_tool_exceptions("get_team_leave")
    async def get_team_leave(
        self,
        ctx: RequestContext,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        """Returns pending and approved leave of requester's direct reports overlapping the date range."""
        if not can_manage_team_leave(ctx):
            return {"status": "error", "error_message": "Only managers can view team leave."}

        reports = self._get_direct_report_ids(ctx.employee_id)
        if not reports:
            return {"status": "success", "team_leave": []}

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            placeholders = ",".join("?" for _ in reports)
            query = f"""
                SELECT lr.request_id, lr.employee_id, e.full_name, lr.leave_type,
                       lr.start_date, lr.end_date, lr.working_days, lr.status
                FROM leave_requests lr
                JOIN employees e ON lr.employee_id = e.employee_id
                WHERE lr.employee_id IN ({placeholders})
                  AND lr.status IN ('pending', 'approved')
                  AND lr.start_date <= ?
                  AND lr.end_date >= ?
                ORDER BY lr.start_date ASC
            """
            params = list(reports) + [end_date, start_date]
            rows = conn.execute(query, params).fetchall()

            team_leaves = []
            for r in rows:
                team_leaves.append(
                    {
                        "request_id": r["request_id"],
                        "employee_id": r["employee_id"],
                        "full_name": r["full_name"],
                        "leave_type": r["leave_type"],
                        "start_date": r["start_date"],
                        "end_date": r["end_date"],
                        "working_days": r["working_days"],
                        "status": r["status"],
                    }
                )
            return {"status": "success", "team_leave": team_leaves}
        finally:
            conn.close()

    def validate_apply_leave_rules(
        self,
        ctx: RequestContext,
        leave_type: str,
        start_date_str: str,
        end_date_str: str,
        today: date,
    ) -> tuple[bool, str, int]:
        """Validate Section 6.2 apply_leave rules in exact sequence, returning (is_valid, error_reason, working_days).

        Validation order:
        1. leave_type in {annual, sick}
        2. whole days (checked by date strings)
        3. both dates in 2026
        4. start >= today
        5. end >= start
        6. zero working days
        7. insufficient balance
        8. overlap with own pending/approved requests
        """
        lt = leave_type.strip().lower() if leave_type else ""
        if lt not in ["annual", "sick"]:
            return False, "leave_type must be either 'annual' or 'sick'.", 0

        # Parse dates
        try:
            s_date = date.fromisoformat(start_date_str.strip())
            e_date = date.fromisoformat(end_date_str.strip())
        except ValueError:
            return False, "Invalid date format. Expected YYYY-MM-DD.", 0

        if s_date.year != 2026 or e_date.year != 2026:
            return False, "Leave dates must both fall within the 2026 calendar year.", 0

        if s_date < today:
            return False, f"Start date ({s_date}) cannot be in the past (today is {today}).", 0

        if e_date < s_date:
            return False, f"End date ({e_date}) cannot be before start date ({s_date}).", 0

        # Compute working days
        working_days = self.workday_calc.count_working_days(
            start_date=s_date,
            end_date=e_date,
            region=ctx.region,
            reference_date=today,
        )

        if working_days <= 0:
            return False, "Selected date range contains zero working days.", 0

        # Check balance and overlaps in database
        conn = sqlite3.connect(self.db_path)
        try:
            # Check balance
            bal_row = conn.execute(
                "SELECT balance_days FROM leave_balances WHERE employee_id = ? AND leave_type = ?",
                (ctx.employee_id, lt),
            ).fetchone()
            curr_balance = float(bal_row[0]) if bal_row else 0.0

            if working_days > curr_balance:
                return (
                    False,
                    f"Insufficient leave balance. Requested {working_days} days, but remaining balance is {curr_balance} days.",
                    0,
                )

            # Check overlap with existing pending or approved requests
            overlap_row = conn.execute(
                """
                SELECT request_id, start_date, end_date FROM leave_requests
                WHERE employee_id = ?
                  AND status IN ('pending', 'approved')
                  AND start_date <= ?
                  AND end_date >= ?
                LIMIT 1
                """,
                (ctx.employee_id, e_date.isoformat(), s_date.isoformat()),
            ).fetchone()

            if overlap_row:
                return (
                    False,
                    f"Leave request overlaps with existing {overlap_row[1]} to {overlap_row[2]} request ({overlap_row[0]}).",
                    0,
                )

            return True, "", working_days

        finally:
            conn.close()

    def execute_apply_leave_transaction(
        self,
        ctx: RequestContext,
        leave_type: str,
        start_date_str: str,
        end_date_str: str,
        today: date,
    ) -> dict[str, Any]:
        """Execute apply_leave in ONE atomic BEGIN IMMEDIATE SQLite transaction."""
        lt = leave_type.strip().lower()
        s_date = date.fromisoformat(start_date_str.strip())
        e_date = date.fromisoformat(end_date_str.strip())

        conn = sqlite3.connect(self.db_path, timeout=30.0)
        try:
            conn.execute("BEGIN IMMEDIATE;")

            # 1. Re-validate within transaction
            bal_row = conn.execute(
                "SELECT balance_days FROM leave_balances WHERE employee_id = ? AND leave_type = ?",
                (ctx.employee_id, lt),
            ).fetchone()
            curr_bal = float(bal_row[0]) if bal_row else 0.0

            working_days = self.workday_calc.count_working_days(s_date, e_date, ctx.region, today)
            if working_days <= 0:
                conn.execute("ROLLBACK;")
                return {
                    "status": "error",
                    "error_message": "Selected range contains zero working days.",
                }

            if working_days > curr_bal:
                conn.execute("ROLLBACK;")
                return {
                    "status": "error",
                    "error_message": f"Insufficient balance ({curr_bal} days available).",
                }

            # Overlap check
            overlap = conn.execute(
                """
                SELECT request_id FROM leave_requests
                WHERE employee_id = ? AND status IN ('pending', 'approved')
                  AND start_date <= ? AND end_date >= ?
                """,
                (ctx.employee_id, e_date.isoformat(), s_date.isoformat()),
            ).fetchone()
            if overlap:
                conn.execute("ROLLBACK;")
                return {"status": "error", "error_message": f"Overlaps with request {overlap[0]}."}

            # 2. Insert request with random unguessable UUID4
            request_id = str(uuid.uuid4())
            now_iso = date.today().isoformat()
            conn.execute(
                """
                INSERT INTO leave_requests (request_id, employee_id, leave_type, start_date, end_date, working_days, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    request_id,
                    ctx.employee_id,
                    lt,
                    s_date.isoformat(),
                    e_date.isoformat(),
                    working_days,
                    now_iso,
                ),
            )

            # 3. Deduct working days from balance
            new_bal = curr_bal - working_days
            conn.execute(
                """
                UPDATE leave_balances
                SET balance_days = ?
                WHERE employee_id = ? AND leave_type = ?
                """,
                (new_bal, ctx.employee_id, lt),
            )

            conn.execute("COMMIT;")
            logger.info(
                "Created leave request",
                request_id=request_id,
                employee_id=ctx.employee_id,
                working_days=working_days,
            )

            return {
                "status": "success",
                "request_id": request_id,
                "leave_type": lt,
                "start_date": s_date.isoformat(),
                "end_date": e_date.isoformat(),
                "working_days": working_days,
                "remaining_balance": new_bal,
            }

        except Exception as e:
            conn.execute("ROLLBACK;")
            logger.error("Failed to execute apply_leave transaction", error=str(e))
            return {"status": "error", "error_message": f"Database transaction failed: {e}"}
        finally:
            conn.close()

    def execute_cancel_leave_transaction(
        self,
        ctx: RequestContext,
        request_id: str,
        today: date,
    ) -> dict[str, Any]:
        """Execute cancel_leave in ONE atomic BEGIN IMMEDIATE SQLite transaction.

        Rules from Section 6.3:
        - Own request only
        - status pending or approved
        - start_date > today
        - Compare-and-swap status to cancelled and refund working_days to balance.
        """
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE;")

            # 1. Fetch request
            row = conn.execute(
                "SELECT * FROM leave_requests WHERE request_id = ?",
                (request_id.strip(),),
            ).fetchone()

            if not row:
                conn.execute("ROLLBACK;")
                return {
                    "status": "error",
                    "error_message": f"Leave request '{request_id}' not found.",
                }

            if row["employee_id"] != ctx.employee_id:
                conn.execute("ROLLBACK;")
                return {
                    "status": "error",
                    "error_message": "You can only cancel your own leave requests.",
                }

            if row["status"] not in ["pending", "approved"]:
                conn.execute("ROLLBACK;")
                return {
                    "status": "error",
                    "error_message": f"Request {request_id} has status '{row['status']}' and cannot be cancelled.",
                }

            start_dt = date.fromisoformat(row["start_date"])
            if start_dt <= today:
                conn.execute("ROLLBACK;")
                return {
                    "status": "error",
                    "error_message": f"Cannot cancel leave that has already started or begins today ({row['start_date']}).",
                }

            working_days = int(row["working_days"])
            leave_type = row["leave_type"]

            # 2. Compare-and-swap status to cancelled
            cursor = conn.execute(
                """
                UPDATE leave_requests
                SET status = 'cancelled'
                WHERE request_id = ? AND status IN ('pending', 'approved')
                """,
                (request_id.strip(),),
            )
            if cursor.rowcount != 1:
                conn.execute("ROLLBACK;")
                return {
                    "status": "error",
                    "error_message": "Concurrent modification detected. Cancellation aborted.",
                }

            # 3. Refund working_days to balance
            conn.execute(
                """
                UPDATE leave_balances
                SET balance_days = balance_days + ?
                WHERE employee_id = ? AND leave_type = ?
                """,
                (working_days, ctx.employee_id, leave_type),
            )

            conn.execute("COMMIT;")
            logger.info(
                "Cancelled leave request",
                request_id=request_id,
                employee_id=ctx.employee_id,
                refunded_days=working_days,
            )

            return {
                "status": "success",
                "request_id": request_id,
                "refunded_working_days": working_days,
            }

        except Exception as e:
            conn.execute("ROLLBACK;")
            logger.error("Failed to execute cancel_leave transaction", error=str(e))
            return {"status": "error", "error_message": f"Database transaction failed: {e}"}
        finally:
            conn.close()
