"""Hypothesis property-based tests for working days and date invariants."""

from datetime import date

from hypothesis import given
from hypothesis import strategies as st

from veltrix.domain.dates import resolve_date_phrase
from veltrix.domain.workdays import WorkdayCalculator

# Test date generator within 2026
date_strategy_2026 = st.dates(min_value=date(2026, 1, 1), max_value=date(2026, 12, 31))


@given(d1=date_strategy_2026, d2=date_strategy_2026)
def test_workdays_range_properties(tmp_path_factory, d1: date, d2: date) -> None:
    """Property: working days is always >= 0 and never exceeds the total calendar day span."""
    tmp_path = tmp_path_factory.mktemp("hypothesis_workdays")
    app_db = tmp_path / "hypo_app.db"
    from veltrix.data.db import init_app_db

    init_app_db(app_db)
    calc = WorkdayCalculator(str(app_db))

    start = min(d1, d2)
    end = max(d1, d2)
    total_days = (end - start).days + 1

    workdays = calc.count_working_days(
        start_date=start,
        end_date=end,
        region="IN",
        reference_date=date(2026, 9, 15),
    )

    assert workdays >= 0
    assert workdays <= total_days

    # Property: reversed date order returns 0
    if end > start:
        assert calc.count_working_days(end, start, "IN", date(2026, 9, 15)) == 0


@given(d=date_strategy_2026)
def test_next_friday_property(d: date) -> None:
    """Property: 'next Friday' is always on a Friday (weekday == 4) and strictly after today (1 to 7 days ahead)."""
    resolved = resolve_date_phrase("next Friday", today=d)
    assert isinstance(resolved, date)
    assert resolved.weekday() == 4  # Friday
    delta = (resolved - d).days
    assert 1 <= delta <= 7
