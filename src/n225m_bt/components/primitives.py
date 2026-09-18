"""Small causal features and risk helpers shared between strategy families."""
from __future__ import annotations

from collections import deque

from n225m_bt.components import component
from n225m_bt.domain import Side


@component(id="rolling_range", kind="feature", summary="Prior N observations' high/low, O(1) updates", tags=["breakout", "rolling", "causal"])
class RollingRange:
    """Read bounds BEFORE update(current_high, current_low) to exclude the current bar."""
    def __init__(self, window: int) -> None:
        if window < 1:
            raise ValueError("window must be positive")
        self.window = window
        self.count = 0
        self.highs: deque[tuple[int, int]] = deque()
        self.lows: deque[tuple[int, int]] = deque()

    @property
    def ready(self) -> bool:
        return self.count >= self.window

    @property
    def bounds(self) -> tuple[int, int] | None:
        return (self.highs[0][1], self.lows[0][1]) if self.ready else None

    def update(self, high: int, low: int) -> None:
        index = self.count
        self.count += 1
        while self.highs and self.highs[-1][1] <= high:
            self.highs.pop()
        while self.lows and self.lows[-1][1] >= low:
            self.lows.pop()
        self.highs.append((index, high))
        self.lows.append((index, low))
        while self.highs[0][0] <= index - self.window:
            self.highs.popleft()
        while self.lows[0][0] <= index - self.window:
            self.lows.popleft()


@component(id="rolling_mean", kind="feature", summary="Streaming arithmetic mean with bounded state", tags=["trend", "rolling", "causal"])
class RollingMean:
    def __init__(self, window: int) -> None:
        if window < 1:
            raise ValueError("window must be positive")
        self.window = window
        self.values: deque[float] = deque()
        self.total = 0.0

    def update(self, value: float) -> float | None:
        self.values.append(value)
        self.total += value
        if len(self.values) > self.window:
            self.total -= self.values.popleft()
        return self.total / self.window if len(self.values) == self.window else None


@component(id="tick_bracket", kind="risk", summary="Long/short stop and target from a signal reference", tags=["stop", "target", "ticks"])
def tick_bracket(side: Side, reference: int, stop_ticks: int, target_ticks: int,
                 tick_size: int = 5) -> tuple[int, int]:
    """Levels are anchored to the signal reference, NOT the next unknown fill."""
    if min(stop_ticks, target_ticks, tick_size) <= 0:
        raise ValueError("stop, target and tick size must be positive")
    return (reference - side.sign * stop_ticks * tick_size,
            reference + side.sign * target_ticks * tick_size)
