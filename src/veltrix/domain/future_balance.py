"""Future leave balance projection computed purely in Python arithmetic."""

import sqlite3
from dataclasses import dataclass
from datetime import date

from veltrix.core.logging import get_logger
from veltrix.domain.models import RequestContext

logger = get_logger("future_balance")


@dataclass(frozen=True)
class FutureBalanceProjection:
    """Detailed calculation of future projected balance."""

    employee_id: str
    leave_type: str
    current_balance: float
    target_month: int
    target_year: int
    accrual_rate_per_month: float
    accrued_months: int
    projected_accrual: float
    future_scheduled_days: float
    projected_final_balance: float
    calculation_steps: list[str]


class FutureBalanceCalculator:
    """Calculates future leave balance using safe Python arithmetic (never the LLM).

    Formula:
    Projected Balance = Current Balance + (Monthly Accrual * Remaining Months) - Scheduled Leaves
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = str(db_path)

    def calculate_projected_balance(
        self,
        ctx: RequestContext,
        leave_type: str,
        target_month: int,
        target_year: int,
        today: date,
        accrual_rate_per_month: float = 1.75,  # 21 days annual / 12 months
    ) -> FutureBalanceProjection:
        """Calculate future balance projection showing the complete arithmetic."""
        lt = leave_type.strip().lower()

        # 1. Fetch current remaining balance
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT balance_days FROM leave_balances WHERE employee_id = ? AND leave_type = ?",
                (ctx.employee_id, lt),
            ).fetchone()
            current_balance = float(row[0]) if row else 0.0

            # 2. Compute remaining months to accrue
            # Accrual occurs at end of month for future full months up to target_month
            if target_year == today.year and target_month >= today.month:
                accrued_months = target_month - today.month
            elif target_year > today.year:
                months_in_current_year = 12 - today.month
                months_in_target_year = target_month
                accrued_months = months_in_current_year + months_in_target_year
            else:
                accrued_months = 0

            projected_accrual = round(accrued_months * accrual_rate_per_month, 2)

            # 3. Sum upcoming scheduled leave between today and target date
            target_end_date = f"{target_year:04d}-{target_month:02d}-28"
            sched_row = conn.execute(
                """
                SELECT COALESCE(SUM(working_days), 0)
                FROM leave_requests
                WHERE employee_id = ?
                  AND leave_type = ?
                  AND status IN ('pending', 'approved')
                  AND start_date > ?
                  AND start_date <= ?
                """,
                (ctx.employee_id, lt, today.isoformat(), target_end_date),
            ).fetchone()
            future_scheduled = float(sched_row[0]) if sched_row else 0.0

            # 4. Final arithmetic
            final_projected = round(current_balance + projected_accrual - future_scheduled, 2)

            calculation_steps = [
                f"1. Current balance as of {today}: {current_balance} days",
                f"2. Accrual from {today.strftime('%B')} to month {target_month}: {accrued_months} months × {accrual_rate_per_month} days/month = +{projected_accrual} days",
                f"3. Already approved/pending leave scheduled before target date: -{future_scheduled} days",
                f"4. Projected balance = {current_balance} + {projected_accrual} - {future_scheduled} = {final_projected} days",
            ]

            return FutureBalanceProjection(
                employee_id=ctx.employee_id,
                leave_type=lt,
                current_balance=current_balance,
                target_month=target_month,
                target_year=target_year,
                accrual_rate_per_month=accrual_rate_per_month,
                accrued_months=accrued_months,
                projected_accrual=projected_accrual,
                future_scheduled_days=future_scheduled,
                projected_final_balance=final_projected,
                calculation_steps=calculation_steps,
            )

        finally:
            conn.close()
