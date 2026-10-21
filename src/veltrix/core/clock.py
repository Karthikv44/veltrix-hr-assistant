"""Clock interface and implementations for deterministic date/time handling."""

from datetime import date, datetime
from typing import Protocol


class Clock(Protocol):
    """Protocol for getting current date without direct system datetime calls."""

    def today(self) -> date:
        """Return the current reference date."""
        ...

    def now(self) -> datetime:
        """Return the current reference datetime."""
        ...


class AppClock:
    """Clock driven by APP_TODAY setting or system date."""

    def __init__(self, fixed_today: str | date | None = None) -> None:
        if isinstance(fixed_today, str) and fixed_today.strip():
            self._fixed_date: date | None = date.fromisoformat(fixed_today.strip())
        elif isinstance(fixed_today, date):
            self._fixed_date = fixed_today
        else:
            self._fixed_date = None

    def today(self) -> date:
        if self._fixed_date is not None:
            return self._fixed_date
        return date.today()

    def now(self) -> datetime:
        t = self.today()
        # Midnight of today
        return datetime(t.year, t.month, t.day)
