"""Aggregates high and low over a fixed wall-clock time window."""
from __future__ import annotations

from datetime import datetime

from n225m_bt.components import component


@component(
    id="fixed_range",
    kind="feature",
    summary="Aggregates high/low over a wall-clock window without imputing missing bars",
    tags=["range", "opening_range", "fixed"],
    uses=[],
)
class FixedRange:
    """Fixed wall-clock interval range aggregator with opening bar qualification."""

    def __init__(self, start: datetime, end: datetime) -> None:
        if start >= end:
            raise ValueError("start must be before end")
        self.start = start
        self.end = end
        self.high: int | None = None
        self.low: int | None = None
        self.bar_count = 0
        self.first_bar_seen = False
        self.opening_bar_observed = False
        self.is_finalized = False
        self.is_available = True
        self.diagnostic: str | None = None

    def update(self, ts: datetime, high: int, low: int, is_eligible: bool = True) -> None:
        """Update range candidate bars during [start, end)."""
        if self.is_finalized:
            return

        if not self.first_bar_seen:
            self.first_bar_seen = True
            if ts == self.start and is_eligible:
                self.opening_bar_observed = True
            else:
                self.opening_bar_observed = False
                self.is_available = False
                self.diagnostic = "opening_range_unavailable"

        if ts < self.start:
            return

        if ts >= self.end:
            self.finalize()
            return

        if is_eligible and self.is_available:
            self.high = high if self.high is None else max(self.high, high)
            self.low = low if self.low is None else min(self.low, low)
            self.bar_count += 1

    def finalize(self) -> None:
        """Finalize the opening range once wall-clock reaches or passes the window end."""
        if self.is_finalized:
            return
        self.is_finalized = True
        if not self.opening_bar_observed or self.bar_count == 0 or self.high is None or self.low is None:
            self.is_available = False
            if self.diagnostic is None:
                self.diagnostic = "opening_range_unavailable"
        elif self.high - self.low <= 0:
            self.is_available = False
            self.diagnostic = "non_positive_range_width"

    @property
    def ready(self) -> bool:
        """Return True if the range has been finalized."""
        return self.is_finalized

    @property
    def is_tradable(self) -> bool:
        """Return True if finalized, available, and range width is positive."""
        return (
            self.is_finalized
            and self.is_available
            and self.high is not None
            and self.low is not None
            and (self.high - self.low > 0)
        )

    @property
    def width(self) -> int | None:
        """Return high - low if finalized and available, else None."""
        if self.is_finalized and self.is_available and self.high is not None and self.low is not None:
            return self.high - self.low
        return None
