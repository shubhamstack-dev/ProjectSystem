"""Maps working-day indices to calendar dates.

All scheduling arithmetic is done on integer indices, which keeps weekends and
holidays out of the maths; dates are only produced for display and for reading
typed dates back in. Index 0 is the first working day on or after the project
start. This is the only place weekends and holidays exist.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable


class WorkCalendar:
    def __init__(self, project_start: date, holidays: Iterable[date] | None = None):
        self._start = project_start
        self._holidays = set(holidays or [])
        self._days: list[date] = []
        self._ensure(120)

    def is_working(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self._holidays  # 5 = Saturday, 6 = Sunday

    def _ensure(self, count: int) -> None:
        if len(self._days) >= count:
            return
        d = self._start if not self._days else self._days[-1] + timedelta(days=1)
        guard = 0
        while len(self._days) < count and guard < count * 4 + 800:
            guard += 1
            if self.is_working(d):
                self._days.append(d)
            d += timedelta(days=1)

    def date_of(self, index: int) -> date:
        """Calendar date of a working-day index."""
        if index < 0:
            index = 0
        self._ensure(index + 2)
        return self._days[min(index, len(self._days) - 1)]

    def index_of(self, d: date, horizon: int = 4000) -> int:
        """First working-day index on or after a calendar date. Inverse of date_of."""
        self._ensure(horizon)
        for i, day in enumerate(self._days):
            if day >= d:
                return i
        return len(self._days) - 1
