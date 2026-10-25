"""Hybrid pipeline coordinating policy retrieval, leave tool queries, and future calculations."""

from datetime import date

from veltrix.core.logging import get_logger
from veltrix.domain.future_balance import FutureBalanceCalculator
from veltrix.domain.models import Citation, RequestContext, ToolCallRecord
from veltrix.orchestration.pipelines.rag import RagPipeline
from veltrix.tools.leave import LeaveTools

logger = get_logger("hybrid_pipeline")


class HybridPipeline:
    """Executes questions that require BOTH policy documents AND employee leave tool data.

    Invariants for route 'hybrid':
    - citations >= 1
    - tool_calls >= 1
    """

    def __init__(
        self,
        rag_pipeline: RagPipeline,
        leave_tools: LeaveTools,
        db_path: str,
    ) -> None:
        self.rag_pipeline = rag_pipeline
        self.leave_tools = leave_tools
        self.future_calc = FutureBalanceCalculator(db_path)

    async def execute(
        self,
        query: str,
        ctx: RequestContext,
        today: date,
        leave_type: str | None = None,
        target_month: int | None = None,
    ) -> tuple[str, list[Citation], list[ToolCallRecord]]:
        """Process hybrid inquiry by retrieving documents and invoking leave tools."""
        lt = leave_type or "annual"

        # 1. Fetch current balance via tool
        bal_res = await self.leave_tools.get_leave_balance(
            ctx=ctx, employee_id=ctx.employee_id, leave_type=lt
        )
        tool_call = ToolCallRecord(
            name="get_leave_balance",
            args={"employee_id": ctx.employee_id, "leave_type": lt},
            status="success" if bal_res.get("status") == "success" else "error",
        )

        # 2. Retrieve document evidence & citations (accrual / carry forward policies)
        rag_answer, citations, _ = await self.rag_pipeline.execute(
            query=f"{lt} leave accrual and carry forward policy",
            ctx=ctx,
            reference_date=today,
        )

        # 3. Handle projection if target month provided by classifier
        if target_month is not None:
            projection = self.future_calc.calculate_projected_balance(
                ctx=ctx,
                leave_type=lt,
                target_month=target_month,
                target_year=2026,
                today=today,
            )
            calc_text = "\n".join(projection.calculation_steps)
            answer = (
                f"Based on company accrual policies and your current balance, here is your projected {lt} leave by month {target_month}:\n\n"
                f"{calc_text}\n\n"
                f"Policy Summary: {rag_answer}"
            )
        else:
            curr_val = bal_res.get("balances", {}).get(lt, 0.0)
            answer = (
                f"Your current {lt} leave balance is {curr_val} days.\n\n"
                f"Policy details: {rag_answer}"
            )

        return answer, citations, [tool_call]
