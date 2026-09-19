"""Strict upper/lower threshold comparison for breakout detection."""
from __future__ import annotations

from n225m_bt.components import component
from n225m_bt.domain import Side


@component(
    id="threshold_cross",
    kind="feature",
    summary="Strict upper and lower threshold cross comparison for breakout detection",
    tags=["threshold", "breakout", "comparison"],
    uses=[],
)
class ThresholdCross:
    """Strict upper/lower threshold comparison without requiring prior bar to be inside."""

    def __init__(self, upper: float | None = None, lower: float | None = None) -> None:
        self.upper = upper
        self.lower = lower

    def is_above(self, value: float | int) -> bool:
        """Return True if value strictly exceeds the upper threshold."""
        return self.upper is not None and value > self.upper

    def is_below(self, value: float | int) -> bool:
        """Return True if value strictly falls below the lower threshold."""
        return self.lower is not None and value < self.lower

    def classify(self, value: float | int, direction: str = "both") -> Side | None:
        """Classify value into Side.LONG, Side.SHORT, or None matching direction."""
        if direction in {"long", "both"} and self.is_above(value):
            return Side.LONG
        if direction in {"short", "both"} and self.is_below(value):
            return Side.SHORT
        return None
