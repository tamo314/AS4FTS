"""Session-local directional efficiency of a close-to-close window against prior ranges."""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta

from n225m_bt.components import component

_CONFIRMATION_LAG = timedelta(minutes=1)


@dataclass(frozen=True, slots=True)
class DirectionalEfficiencyResult:
    impulse: int
    efficiency: float
    width: int
    prior_range_median: float


@component(
    id="directional_efficiency",
    kind="feature",
    summary="Directional efficiency of a trailing close-to-close window against the median range of the three preceding windows",
    tags=["efficiency", "impulse", "session", "directional"],
    uses=[],
)
class DirectionalEfficiency:
    """Session-local directional efficiency ratio with a prior three-window range median.

    Call reset(session_open) once at the start of each session, then update(ts_jst,
    high, low, close, is_eligible) for every confirmed bar as it is observed, keyed
    by that bar's own start timestamp. Each bar's confirmation instant is treated as
    ts_jst + 1 minute, the same convention used by range_compression. Call
    evaluate(d, window_minutes) once a bar has just confirmed at instant d to score
    the window ending at d: collect eligible bars whose confirmation instant falls
    in the closed interval [d-w, d], ordered by time. I is the last observed close
    minus the first, W = abs(I), and E = W divided by the sum of absolute
    differences between consecutive observed closes in that span (the close-to-close
    path length). Also computes the median width (high - low) of the three
    preceding, non-overlapping windows R1 = [d-2w, d-w), R2 = [d-3w, d-2w),
    R3 = [d-4w, d-3w), each built from observed highs/lows of eligible bars only.
    Missing or non-eligible bars are never imputed. Returns None whenever fewer
    than 4*w wall-clock minutes have elapsed since the session open, the path's
    first observed confirmation instant is not exactly d-w or its last is not
    exactly d, the close-to-close path length is not strictly positive, W is not
    strictly positive, any of R1..R3 spills before the session open, or any of
    R1..R3 has no eligible bar.
    """

    def __init__(self) -> None:
        self.session_open: datetime | None = None
        self._observations: list[tuple[datetime, int, int, int, bool]] = []

    def reset(self, session_open: datetime) -> None:
        """Start a fresh session-local observation buffer anchored at session_open."""
        self.session_open = session_open
        self._observations = []

    def update(self, ts_jst: datetime, high: int, low: int, close: int, is_eligible: bool) -> None:
        """Record one confirmed bar's own start timestamp, high, low, close, and eligibility."""
        self._observations.append((ts_jst, high, low, close, is_eligible))

    def _range_extent(self, start: datetime, end: datetime) -> tuple[int, int] | None:
        high: int | None = None
        low: int | None = None
        for ts_jst, h, l, _c, is_eligible in self._observations:
            if not is_eligible or ts_jst < start or ts_jst >= end:
                continue
            high = h if high is None else max(high, h)
            low = l if low is None else min(low, l)
        return None if high is None or low is None else (high, low)

    def _close_path(self, start: datetime, end: datetime) -> list[tuple[datetime, int]]:
        path = [
            (ts_jst + _CONFIRMATION_LAG, close)
            for ts_jst, _h, _l, close, is_eligible in self._observations
            if is_eligible and start <= ts_jst + _CONFIRMATION_LAG <= end
        ]
        path.sort(key=lambda item: item[0])
        return path

    def evaluate(self, d: datetime, window_minutes: int) -> DirectionalEfficiencyResult | None:
        """Return directional efficiency stats for the window ending at confirmation instant d."""
        if self.session_open is None:
            return None
        w = timedelta(minutes=window_minutes)
        if d - 4 * w < self.session_open:
            return None
        start = d - w

        path = self._close_path(start, d)
        if len(path) < 2 or path[0][0] != start or path[-1][0] != d:
            return None

        closes = [close for _ts, close in path]
        impulse = closes[-1] - closes[0]
        denominator = sum(abs(b - a) for a, b in zip(closes, closes[1:]))
        if denominator <= 0:
            return None
        width = abs(impulse)
        if width <= 0:
            return None
        efficiency = width / denominator

        widths: list[int] = []
        for i in range(1, 4):
            end = d - i * w
            window_start = end - w
            extent = self._range_extent(window_start, end)
            if extent is None:
                return None
            widths.append(extent[0] - extent[1])
        prior_range_median = statistics.median(widths)

        return DirectionalEfficiencyResult(
            impulse=impulse,
            efficiency=efficiency,
            width=width,
            prior_range_median=prior_range_median,
        )
