"""Calendar-driven working days calculation deducting weekends and public holidays."""

import sqlite3
from datetime import date, timedelta

from veltrix.core.logging import get_logger
from veltrix.domain.precedence import PolicyClaim, PrecedenceResolver

logger = get_logger("workdays")


class WorkdayCalculator:
    """Calculates working days strictly from Monday-Friday excluding regional public holidays."""

    def __init__(self, app_db_path: str) -> None:
        self.app_db_path = str(app_db_path)

    def get_public_holidays_for_region(
        self, region: str, reference_date: date, year: int = 2026
    ) -> set[date]:
        """Resolve the winning holiday calendar document for the region and fetch its public holidays."""
        conn = sqlite3.connect(self.app_db_path)
        try:
            # 1. Fetch all distinct calendar doc_ids from chunks table for this region
            region_col = f"region_{region.upper()}"
            query = f"""
                SELECT DISTINCT doc_id, doc_type, effective_date, region_GLOBAL, region_IN, region_US, region_DE
                FROM chunks
                WHERE doc_type = 'calendar'
                  AND (region_GLOBAL = 1 OR {region_col} = 1)
            """
            rows = conn.execute(query).fetchall()

            if not rows:
                logger.warning("No calendar documents found in app.db", region=region)
                return set()

            # Build claims to resolve winning calendar via Section 5 precedence
            claims: list[PolicyClaim] = []
            for r in rows:
                doc_id, doc_type, eff_date, r_global, r_in, r_us, r_de = r
                doc_regions = []
                if r_global:
                    doc_regions.append("GLOBAL")
                if r_in:
                    doc_regions.append("IN")
                if r_us:
                    doc_regions.append("US")
                if r_de:
                    doc_regions.append("DE")

                claims.append(
                    PolicyClaim(
                        group_id="holiday_calendar",
                        doc_id=doc_id,
                        doc_type=doc_type,
                        regions=tuple(doc_regions),
                        effective_date=eff_date,
                        locator="p. 1",
                        value=doc_id,
                    )
                )

            # Resolve winning calendar at reference_date
            decision = PrecedenceResolver.resolve(
                group_id="holiday_calendar",
                all_claims=claims,
                user_region=region,
                reference_date=reference_date,
            )

            winning_doc_id = decision.winning_claim.doc_id if decision.winning_claim else None
            if not winning_doc_id:
                logger.warning("Could not resolve winning calendar document", region=region)
                return set()

            # 2. Fetch public holidays from winning calendar for the specified year
            holiday_rows = conn.execute(
                """
                SELECT date FROM holidays
                WHERE doc_id = ? AND kind = 'public'
                """,
                (winning_doc_id,),
            ).fetchall()

            holiday_dates: set[date] = set()
            for (d_str,) in holiday_rows:
                try:
                    dt = date.fromisoformat(d_str)
                    if dt.year == year:
                        holiday_dates.add(dt)
                except ValueError:
                    continue

            return holiday_dates

        finally:
            conn.close()

    def count_working_days(
        self,
        start_date: date,
        end_date: date,
        region: str,
        reference_date: date,
    ) -> int:
        """Count working days in inclusive range [start_date, end_date].

        Working days = Mon-Fri minus public holidays from winning calendar.
        """
        if end_date < start_date:
            return 0

        holidays = self.get_public_holidays_for_region(
            region=region, reference_date=reference_date, year=start_date.year
        )

        working_days = 0
        curr = start_date
        while curr <= end_date:
            # 0 = Monday, ..., 4 = Friday, 5 = Saturday, 6 = Sunday
            if curr.weekday() < 5 and curr not in holidays:
                working_days += 1
            curr += timedelta(days=1)

        return working_days
