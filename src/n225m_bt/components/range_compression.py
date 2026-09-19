"""Session-local sliding wall-clock range compression detector across four half-open windows."""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta

from n225m_bt.components import component


@dataclass(frozen=True, slots=True)
class CompressionRange:
    high: int
    low: int
    width: int


@component(
    id="range_compression",
    kind="feature",
    summary="Detects a trailing wall-clock range contraction against the median of the three preceding windows",
    tags=["range", "compression", "breakout", "session"],
    uses=[],
)
class RangeCompression:
    """Evaluates four half-open wall-clock windows against session-local timestamped OHLC.

    Call reset(session_open) once at the start of each session, then update(ts_jst,
    high, low, is_eligible) for every bar as it is observed, keyed by that bar's own
    start timestamp. Call evaluate(d, window_minutes, compression_ratio) once a bar
    has just confirmed to test R0 = [d-w, d) against the median width of
    R1 = [d-2w, d-w), R2 = [d-3w, d-2w), R3 = [d-4w, d-3w). The caller supplies d as
    that bar's confirmation instant (for 1-minute bars, ts_jst + 1 minute); because a
    bar's own ts_jst then falls strictly inside its own trailing R0 window while
    older bars fall into R1..R3, no separate lag bookkeeping is needed here. All four
    windows must lie at or after the session open and each must contain at least one
    eligible bar; missing or non-eligible bars are never imputed and observed bar
    counts are never substituted for elapsed wall-clock minutes. Returns None
    whenever any window is empty, spills before the session open, or the contraction
    condition W/M <= compression_ratio is not met.
    """

    def __init__(self) -> None:
        self.session_open: datetime | None = None
        self._observations: list[tuple[datetime, int, int, bool]] = []

    def reset(self, session_open: datetime) -> None:
        """Start a fresh session-local observation buffer anchored at session_open."""
        self.session_open = session_open
        self._observations = []

    def update(self, ts_jst: datetime, high: int, low: int, is_eligible: bool) -> None:
        """Record one bar's own start timestamp, high, low, and eligibility flag."""
        self._observations.append((ts_jst, high, low, is_eligible))

    def _extent(self, start: datetime, end: datetime) -> tuple[int, int] | None:
        high: int | None = None
        low: int | None = None
        for ts_jst, h, l, is_eligible in self._observations:
            if not is_eligible or ts_jst < start or ts_jst >= end:
                continue
            high = h if high is None else max(high, h)
            low = l if low is None else min(low, l)
        return None if high is None or low is None else (high, low)

    def evaluate(
        self, d: datetime, window_minutes: int, compression_ratio: float
    ) -> CompressionRange | None:
        """Return the compressed R0 candidate at confirmation instant d, or None."""
        if self.session_open is None:
            return None
        w = timedelta(minutes=window_minutes)
        if d - 4 * w < self.session_open:
            return None

        extents: list[tuple[int, int]] = []
        for i in range(4):
            end = d - i * w
            start = end - w
            extent = self._extent(start, end)
            if extent is None:
                return None
            extents.append(extent)

        widths = [h - l for h, l in extents]
        r0_width = widths[0]
        if r0_width <= 0:
            return None
        median_width = statistics.median(widths[1:])
        if median_width <= 0 or r0_width / median_width > compression_ratio:
            return None

        r0_high, r0_low = extents[0]
        return CompressionRange(high=r0_high, low=r0_low, width=r0_width)
