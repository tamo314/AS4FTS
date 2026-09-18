"""Parameterized example composed from shared primitives; not an alpha claim."""
from __future__ import annotations

from datetime import date
from typing import Any

from n225m_bt.components import component
from n225m_bt.components.primitives import RollingRange, tick_bracket
from n225m_bt.domain import Bar, Session, Side, Signal, SignalAction
from n225m_bt.strategies.base import StrategyContext


@component(id="range_breakout", kind="strategy", summary="Prior-window breakout with tick brackets and per-session reset", tags=["breakout", "example"], uses=["rolling_range", "tick_bracket"])
class RangeBreakout:
    strategy_id = "range_breakout"
    strategy_version = "1"

    def __init__(self, lookback: int, stop_ticks: int, target_ticks: int,
                 direction: str = "both", tick_size: int = 5) -> None:
        if direction not in {"long", "short", "both"}:
            raise ValueError("direction must be long, short, or both")
        if min(lookback, stop_ticks, target_ticks, tick_size) <= 0:
            raise ValueError("numeric parameters must be positive")
        self.lookback, self.stop_ticks, self.target_ticks = lookback, stop_ticks, target_ticks
        self.direction, self.tick_size = direction, tick_size
        self.window = RollingRange(lookback)
        self.session: tuple[date, Session] | None = None

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> Signal | None:
        key = (bar.trade_date, bar.session)
        if key != self.session:
            self.window = RollingRange(self.lookback)
            self.session = key
        bounds = self.window.bounds
        self.window.update(bar.high, bar.low)
        if ctx.has_position or bounds is None:
            return None
        high, low = bounds
        side = None
        if bar.close > high and self.direction in {"long", "both"}:
            side = Side.LONG
        elif bar.close < low and self.direction in {"short", "both"}:
            side = Side.SHORT
        if side is None:
            return None
        stop, target = tick_bracket(side, bar.close, self.stop_ticks, self.target_ticks, self.tick_size)
        action = SignalAction.ENTER_LONG if side is Side.LONG else SignalAction.ENTER_SHORT
        return Signal(action, bar.ts_jst, stop, target, "prior_window_breakout")


def create_strategy(parameters: dict[str, Any]) -> RangeBreakout:
    return RangeBreakout(**parameters)
