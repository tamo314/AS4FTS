"""Thin adapter fading single discrete excursions from a prior rolling mean."""
from __future__ import annotations

from datetime import date
from typing import Any

from n225m_bt.components import component
from n225m_bt.components.primitives import RollingMean, tick_bracket
from n225m_bt.domain import Bar, Session, Side, Signal, SignalAction
from n225m_bt.strategies.base import StrategyContext


@component(id="mean_excursion_fade", kind="strategy",
           summary="Fades single discrete excursions from a prior session-local rolling mean with tick brackets",
           tags=["mean_reversion", "excursion", "example"],
           uses=["rolling_mean", "tick_bracket"])
class MeanExcursionFade:
    strategy_id = "mean_excursion_fade"
    strategy_version = "1"

    def __init__(self, mean_window: int, entry_ticks: int, stop_ticks: int, target_ticks: int,
                 direction: str = "both", rearm_mode: str = "inside_band", tick_size: int = 5) -> None:
        if direction not in {"long", "short", "both"}:
            raise ValueError("direction must be long, short, or both")
        if rearm_mode not in {"inside_band", "cross_mean"}:
            raise ValueError("rearm_mode must be inside_band or cross_mean")
        if min(mean_window, entry_ticks, stop_ticks, target_ticks, tick_size) <= 0:
            raise ValueError("numeric parameters must be positive")
        self.mean_window, self.entry_ticks = mean_window, entry_ticks
        self.stop_ticks, self.target_ticks = stop_ticks, target_ticks
        self.direction, self.rearm_mode, self.tick_size = direction, rearm_mode, tick_size
        self.mean = RollingMean(mean_window)
        self.session: tuple[date, Session] | None = None
        self.arm_upper = True
        self.arm_lower = True

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> Signal | None:
        key = (bar.trade_date, bar.session)
        if key != self.session:
            self.mean = RollingMean(self.mean_window)
            self.session = key
            self.arm_upper = True
            self.arm_lower = True

        prior_mean = self.mean.mean
        self.mean.update(bar.close)
        if prior_mean is None:
            return None

        upper = prior_mean + self.entry_ticks * self.tick_size
        lower = prior_mean - self.entry_ticks * self.tick_size
        above_upper = bar.close >= upper
        below_lower = bar.close <= lower

        side: Side | None = None
        if above_upper and self.arm_upper:
            side = Side.SHORT
        if below_lower and self.arm_lower and side is None:
            side = Side.LONG

        if above_upper:
            self.arm_upper = False
        if below_lower:
            self.arm_lower = False

        if self.rearm_mode == "inside_band":
            if not above_upper:
                self.arm_upper = True
            if not below_lower:
                self.arm_lower = True
        else:
            if bar.close <= prior_mean:
                self.arm_upper = True
            if bar.close >= prior_mean:
                self.arm_lower = True

        if side is None or self.direction not in {side.value, "both"}:
            return None
        if ctx.has_position:
            return None

        stop, target = tick_bracket(side, bar.close, self.stop_ticks, self.target_ticks, self.tick_size)
        action = SignalAction.ENTER_LONG if side is Side.LONG else SignalAction.ENTER_SHORT
        return Signal(action, bar.ts_jst, stop, target, "mean_excursion_fade")


def create_strategy(parameters: dict[str, Any]) -> MeanExcursionFade:
    return MeanExcursionFade(**parameters)
