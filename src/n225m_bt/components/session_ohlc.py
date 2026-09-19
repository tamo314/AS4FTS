"""Builds a completed OHLC bar for one wall-clock session window from observed bars."""
from __future__ import annotations

from datetime import datetime

from n225m_bt.components import component


@component(
    id="session_ohlc",
    kind="feature",
    summary="Builds trade-date OHLC from eligible bars observed within an explicit session boundary",
    tags=["session", "ohlc", "aggregation"],
    uses=[],
)
class SessionOHLC:
    """Completed open/high/low/close built only from eligible bars inside [start, end].

    Call update(ts, open_, high, low, close, is_eligible) for every bar as it is
    observed while it falls within the closed interval [start, end]; bars outside
    that interval or flagged non-eligible are ignored and never imputed. Open is
    taken from the first eligible bar observed in time order and close from the
    last, so a missing official boundary bar is never backfilled from another
    period's value. High/low are the running max/min of eligible bars' own
    high/low. Call finalize() once no further bars for this window can arrive
    (e.g. the next session has started) to lock in the result; is_available is
    False whenever no eligible bar was ever observed. is_tradable additionally
    requires the finalized window to have a strictly positive high-low width.
    """

    def __init__(self, start: datetime, end: datetime) -> None:
        if start >= end:
            raise ValueError("start must be before end")
        self.start = start
        self.end = end
        self.open: int | None = None
        self.high: int | None = None
        self.low: int | None = None
        self.close: int | None = None
        self.bar_count = 0
        self.is_finalized = False
        self.is_available = True
        self.diagnostic: str | None = None

    def update(self, ts: datetime, open_: int, high: int, low: int, close: int,
               is_eligible: bool = True) -> None:
        """Fold one observed bar into the window if it is eligible and in range."""
        if self.is_finalized or not is_eligible:
            return
        if ts < self.start or ts > self.end:
            return
        if self.open is None:
            self.open = open_
        self.high = high if self.high is None else max(self.high, high)
        self.low = low if self.low is None else min(self.low, low)
        self.close = close
        self.bar_count += 1

    def finalize(self) -> None:
        """Lock in the result once no further bars for this window will arrive."""
        if self.is_finalized:
            return
        self.is_finalized = True
        if (self.bar_count == 0 or self.open is None or self.close is None
                or self.high is None or self.low is None):
            self.is_available = False
            self.diagnostic = "session_ohlc_unavailable"
        elif self.high - self.low <= 0:
            self.is_available = False
            self.diagnostic = "non_positive_range_width"

    @property
    def is_tradable(self) -> bool:
        """Return True if finalized, available, and the high-low width is positive."""
        return (
            self.is_finalized and self.is_available
            and self.high is not None and self.low is not None
            and (self.high - self.low > 0)
        )

    @property
    def width(self) -> int | None:
        """Return high - low if finalized, available, and positive, else None."""
        if self.is_tradable:
            return self.high - self.low  # type: ignore[operator]
        return None
