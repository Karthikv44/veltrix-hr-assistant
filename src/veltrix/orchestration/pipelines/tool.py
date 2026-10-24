"""Tool pipeline handling read-only tools, dry-run write proposals, and atomic confirmation execution."""

import re
import sqlite3
from datetime import date, timedelta

from veltrix.api.schemas import ChatResponse
from veltrix.core.logging import get_logger
from veltrix.data.sessions import SessionManager
from veltrix.domain.models import RequestContext, ToolCallRecord
from veltrix.orchestration.assembler import Assembler
from veltrix.orchestration.confirm import ConfirmationStateMachine
from veltrix.tools.leave import LeaveTools

logger = get_logger("tool_pipeline")


class ToolPipeline:
    """Orchestrates leave tools and the two-step confirmation state machine."""

    def __init__(
        self,
        leave_tools: LeaveTools,
        session_manager: SessionManager,
    ) -> None:
        self.leave_tools = leave_tools
        self.session_manager = session_manager
        self.state_machine = ConfirmationStateMachine(session_manager)

    async def execute_or_propose(
        self,
        session_id: str,
        message: str,
        ctx: RequestContext,
        today: date,
    ) -> ChatResponse:
        """Route tool inquiries, write proposals, or confirmations."""
        text = message.strip().lower()

        # 1. Check if there is a pending proposal waiting for confirmation
        pending_proposal = self.state_machine.get_pending_proposal(session_id)
        if pending_proposal is not None:
            if self.state_machine.is_confirmation(text):
                # User confirmed -> Execute in ONE atomic transaction
                self.state_machine.clear_proposal(session_id)

                if pending_proposal.action_type == "apply_leave":
                    p = pending_proposal.payload
                    res = self.leave_tools.execute_apply_leave_transaction(
                        ctx=ctx,
                        leave_type=p["leave_type"],
                        start_date_str=p["start_date"],
                        end_date_str=p["end_date"],
                        today=today,
                    )
                    status = "success" if res.get("status") == "success" else "error"
                    tool_record = ToolCallRecord(
                        name="apply_leave",
                        args={
                            "leave_type": p["leave_type"],
                            "start_date": p["start_date"],
                            "end_date": p["end_date"],
                        },
                        status=status,
                    )

                    if status == "success":
                        answer = (
                            f"Your leave request has been submitted successfully (Request ID: {res['request_id']}). "
                            f"{res['working_days']} working days have been deducted. Remaining balance: {res['remaining_balance']} days."
                        )
                    else:
                        answer = f"Unable to submit leave request: {res.get('error_message')}"

                    return Assembler.assemble_response(
                        answer=answer,
                        intended_route="tool",
                        tool_calls=[tool_record],
                        pending_confirmation=False,
                    )

                elif pending_proposal.action_type == "cancel_leave":
                    p = pending_proposal.payload
                    res = self.leave_tools.execute_cancel_leave_transaction(
                        ctx=ctx,
                        request_id=p["request_id"],
                        today=today,
                    )
                    status = "success" if res.get("status") == "success" else "error"
                    tool_record = ToolCallRecord(
                        name="cancel_leave",
                        args={"request_id": p["request_id"]},
                        status=status,
                    )
                    if status == "success":
                        answer = f"Leave request {p['request_id']} has been cancelled. {res['refunded_working_days']} working days refunded to your balance."
                    else:
                        answer = f"Unable to cancel request: {res.get('error_message')}"

                    return Assembler.assemble_response(
                        answer=answer,
                        intended_route="tool",
                        tool_calls=[tool_record],
                        pending_confirmation=False,
                    )

            elif self.state_machine.is_cancellation(text):
                # Explicit cancellation of proposal
                self.state_machine.clear_proposal(session_id)
                return Assembler.assemble_response(
                    answer="Your pending action has been cancelled.",
                    intended_route="tool",
                    tool_calls=[],
                    pending_confirmation=False,
                )

            else:
                # Any other prompt discards the proposal and continues normally
                logger.info(
                    "Discarding unconfirmed proposal due to unrelated prompt", session_id=session_id
                )
                self.state_machine.clear_proposal(session_id)

        # 2. Check for balance queries: get_leave_balance
        if (
            "balance" in text
            or "how many days" in text
            or "pto" in text
            or "quota" in text
            or "remaining" in text
            or "afford" in text
            or "enough days" in text
            or "enough leave" in text
        ):
            # Extract leave_type if specified
            lt = "annual" if "annual" in text else ("sick" if "sick" in text else None)
            res = await self.leave_tools.get_leave_balance(
                ctx=ctx, employee_id=ctx.employee_id, leave_type=lt
            )
            tool_record = ToolCallRecord(
                name="get_leave_balance",
                args={"employee_id": ctx.employee_id, "leave_type": lt}
                if lt
                else {"employee_id": ctx.employee_id},
                status="success" if res.get("status") == "success" else "error",
            )
            if res.get("status") == "success":
                b_parts = [f"{k}: {v} days" for k, v in res["balances"].items()]
                answer = f"Your current remaining leave balance: {', '.join(b_parts)}."
            else:
                answer = res.get("error_message", "Could not fetch balance.")

            return Assembler.assemble_response(
                answer=answer,
                intended_route="tool",
                tool_calls=[tool_record],
            )

        # 3. Check for list leave requests
        if (
            "pending requests" in text
            or "my requests" in text
            or "list leave" in text
            or "leave history" in text
        ):
            res = await self.leave_tools.list_leave_requests(ctx=ctx, employee_id=ctx.employee_id)
            tool_record = ToolCallRecord(
                name="list_leave_requests",
                args={"employee_id": ctx.employee_id},
                status="success" if res.get("status") == "success" else "error",
            )
            reqs = res.get("requests", [])
            if reqs:
                lines = [
                    f"- {r['request_id']}: {r['leave_type']} from {r['start_date']} to {r['end_date']} ({r['working_days']} days, status: {r['status']})"
                    for r in reqs[:5]
                ]
                answer = "Your leave requests:\n" + "\n".join(lines)
            else:
                answer = "You have no recorded leave requests."

            return Assembler.assemble_response(
                answer=answer,
                intended_route="tool",
                tool_calls=[tool_record],
            )

        # 4. Check for team leave: get_team_leave (Managers only)
        if "team leave" in text or "direct reports" in text:
            # Default to rest of 2026 or parse range
            start_dt = today
            end_dt = date(2026, 12, 31)
            res = await self.leave_tools.get_team_leave(
                ctx=ctx, start_date=start_dt.isoformat(), end_date=end_dt.isoformat()
            )
            status = "success" if res.get("status") == "success" else "error"
            tool_record = ToolCallRecord(
                name="get_team_leave",
                args={"start_date": start_dt.isoformat(), "end_date": end_dt.isoformat()},
                status=status,
            )
            if status == "success":
                t_leaves = res.get("team_leave", [])
                if t_leaves:
                    lines = [
                        f"- {tl['full_name']} ({tl['employee_id']}): {tl['leave_type']} {tl['start_date']} to {tl['end_date']} ({tl['working_days']} days)"
                        for tl in t_leaves
                    ]
                    answer = "Team leave schedule:\n" + "\n".join(lines)
                else:
                    answer = "There are no pending or approved leaves scheduled for your team in this period."
            else:
                answer = res.get("error_message", "Unable to view team leave.")

            return Assembler.assemble_response(
                answer=answer,
                intended_route="tool",
                tool_calls=[tool_record],
            )

        # 5. Check for cancel_leave proposal
        if "cancel" in text:
            # Look for request_id (UUID or req_...)
            req_match = re.search(r"\b([a-f0-9-]{36}|req_[a-zA-Z0-9]+)\b", text)
            if not req_match:
                # Need to clarify which request
                res = await self.leave_tools.list_leave_requests(
                    ctx=ctx, employee_id=ctx.employee_id
                )
                reqs = [
                    r for r in res.get("requests", []) if r["status"] in ["pending", "approved"]
                ]
                if not reqs:
                    return Assembler.assemble_response(
                        answer="You have no active pending or approved leave requests to cancel.",
                        intended_route="tool",
                        tool_calls=[],
                    )
                # Route clarify: citations empty, tool_calls empty
                return Assembler.assemble_response(
                    answer=f"Which leave request would you like to cancel? Please provide the request ID from your active requests: {', '.join(r['request_id'] for r in reqs[:3])}.",
                    intended_route="clarify",
                )

            req_id = req_match.group(1)
            # Dry-run validation
            conn = sqlite3.connect(self.leave_tools.db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM leave_requests WHERE request_id = ?", (req_id,)
            ).fetchone()
            conn.close()

            if (
                not row
                or row["employee_id"] != ctx.employee_id
                or row["status"] not in ["pending", "approved"]
                or date.fromisoformat(row["start_date"]) <= today
            ):
                error_reason = "Request not found or not eligible for cancellation (already started or not owned by you)."
                return Assembler.assemble_response(
                    answer=f"Cannot cancel leave: {error_reason}",
                    intended_route="tool",
                    tool_calls=[
                        ToolCallRecord(
                            name="cancel_leave", args={"request_id": req_id}, status="error"
                        )
                    ],
                )

            # Valid -> propose with status pending_confirmation
            self.state_machine.save_proposal(
                session_id=session_id,
                employee_id=ctx.employee_id,
                action_type="cancel_leave",
                payload={"request_id": req_id},
            )
            tool_record = ToolCallRecord(
                name="cancel_leave",
                args={"request_id": req_id},
                status="pending_confirmation",
            )
            summary = f"Are you sure you want to cancel your {row['leave_type']} leave request ({req_id}) from {row['start_date']} to {row['end_date']} ({row['working_days']} days)? Please confirm ('yes' or 'confirm')."

            return Assembler.assemble_response(
                answer=summary,
                intended_route="tool",
                tool_calls=[tool_record],
                pending_confirmation=True,
            )

        # 6. Check for apply_leave proposal
        if "apply" in text or "book" in text or "request" in text:
            # Check leave type
            lt = "annual" if "annual" in text else ("sick" if "sick" in text else None)
            if not lt:
                return Assembler.assemble_response(
                    answer="Would you like to apply for 'annual' leave or 'sick' leave? Please specify the leave type.",
                    intended_route="clarify",
                )

            # Resolve dates
            dates_found = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)
            if len(dates_found) >= 2:
                s_date_str, e_date_str = dates_found[0], dates_found[1]
            elif "next week" in text:
                curr_monday = today - timedelta(days=today.weekday())
                next_mon = curr_monday + timedelta(days=7)
                next_fri = next_mon + timedelta(days=4)
                s_date_str, e_date_str = next_mon.isoformat(), next_fri.isoformat()
            else:
                return Assembler.assemble_response(
                    answer="Please specify the start date and end date for your leave (YYYY-MM-DD).",
                    intended_route="clarify",
                )

            # Dry-run validation
            is_valid, error_reason, working_days = self.leave_tools.validate_apply_leave_rules(
                ctx=ctx,
                leave_type=lt,
                start_date_str=s_date_str,
                end_date_str=e_date_str,
                today=today,
            )

            if not is_valid:
                # Reject immediately with route tool, status error, and NO proposal
                tool_record = ToolCallRecord(
                    name="apply_leave",
                    args={"leave_type": lt, "start_date": s_date_str, "end_date": e_date_str},
                    status="error",
                )
                return Assembler.assemble_response(
                    answer=f"Cannot apply for leave: {error_reason}",
                    intended_route="tool",
                    tool_calls=[tool_record],
                    pending_confirmation=False,
                )

            # Valid dry-run -> store proposal and ask for confirmation
            self.state_machine.save_proposal(
                session_id=session_id,
                employee_id=ctx.employee_id,
                action_type="apply_leave",
                payload={"leave_type": lt, "start_date": s_date_str, "end_date": e_date_str},
            )
            tool_record = ToolCallRecord(
                name="apply_leave",
                args={"leave_type": lt, "start_date": s_date_str, "end_date": e_date_str},
                status="pending_confirmation",
            )
            summary = (
                f"You are requesting {working_days} working days of {lt} leave "
                f"from {s_date_str} to {e_date_str}. Please confirm to proceed ('yes' or 'confirm')."
            )
            return Assembler.assemble_response(
                answer=summary,
                intended_route="tool",
                tool_calls=[tool_record],
                pending_confirmation=True,
            )

        # Default fallback
        return Assembler.assemble_response(
            answer="How can I assist with your leave management? You can check balances, list requests, or apply for leave.",
            intended_route="tool",
            tool_calls=[],
        )
