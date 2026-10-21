"""Calendar date phrase resolver implementing Monday-start weeks and Section 8.4 rules."""

import re
from datetime import date, timedelta

from dateutil import parser as date_parser

from veltrix.core.logging import get_logger

logger = get_logger("dates")

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


class DateResolutionError(ValueError):
    """Raised when a date string cannot be resolved or is ambiguous."""


def resolve_date_phrase(
    phrase: str,
    today: date,
    default_year: int = 2026,
) -> tuple[date, date] | date:
    """Resolve a relative or absolute date phrase into date or date range.

    Rules from Section 8.4:
    - All dates are calendar dates, with no times or time zones.
    - Today is the value of APP_TODAY. A date without a year means 2026.
    - Weeks start on Monday.
    - "Next week" = Monday to Friday of the following week.
    - "Next Friday" = the first Friday after today.
    - If a date phrase is ambiguous or in the past, raises DateResolutionError to prompt clarify.
    """
    cleaned = phrase.strip().lower()

    # 1. "today"
    if cleaned == "today":
        return today

    # 2. "tomorrow"
    if cleaned == "tomorrow":
        return today + timedelta(days=1)

    # 3. "next week" -> Monday to Friday of the following week
    if "next week" in cleaned:
        # Current week Monday
        curr_monday = today - timedelta(days=today.weekday())
        next_monday = curr_monday + timedelta(days=7)
        next_friday = next_monday + timedelta(days=4)
        return next_monday, next_friday

    # 4. "next <weekday>" -> First <weekday> after today
    next_match = re.search(
        r"next\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", cleaned
    )
    if next_match:
        target_wd = WEEKDAYS[next_match.group(1)]
        # Calculate days until next occurrence strictly after today (1 to 7 days)
        days_ahead = (target_wd - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return today + timedelta(days=days_ahead)

    # 5. Direct weekday name without 'next' (e.g. "this Friday" or "Friday")
    for wd_name, wd_idx in WEEKDAYS.items():
        if re.search(rf"\b(?:this\s+)?{wd_name}\b", cleaned) and "next" not in cleaned:
            days_ahead = (wd_idx - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return today + timedelta(days=days_ahead)

    # 6. Absolute date parsing with 2026 default year
    # Check if a year is explicitly present
    has_year = bool(re.search(r"\b20\d\d\b", cleaned))
    parse_str = cleaned if has_year else f"{cleaned} {default_year}"

    try:
        parsed_dt = date_parser.parse(parse_str, default=date(default_year, 1, 1), dayfirst=True)
        res_date = date(parsed_dt.year, parsed_dt.month, parsed_dt.day)
        return res_date
    except Exception as e:
        logger.debug("Failed to parse date phrase", phrase=phrase, error=str(e))
        raise DateResolutionError(f"Cannot resolve date phrase: '{phrase}'") from e
