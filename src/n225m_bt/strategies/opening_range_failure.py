"""H02 v2: bounded range re-entry, inclusive timeout, and later-event rearming.

The legacy opening_range_failure_fade factory remains unchanged for H01-derived
experiments. This factory also accepts its zero-depth parameter names so a saved
H02 specification can be rerun without redesigning its grid.
"""
from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

from n225m_bt.calendar.classifier import CalendarClassifier
from n225m_bt.components import component
from n225m_bt.components.fixed_range import FixedRange
from n225m_bt.components.primitives import tick_bracket
from n225m_bt.components.session_clock import SessionClock
from n225m_bt.domain import Bar, Session, Side, Signal, SignalAction
from n225m_bt.strategies.base import StrategyContext
from n225m_bt.strategies.opening_range_failure_fade import OpeningRangeFailureFade


@component(id="opening_range_failure_h02_v2", kind="strategy",
           summary="H02: return inside both range bounds, inclusive deadline, rearm after expiry",
           tags=["H02", "fade", "opening_range", "versioned"],
           uses=["session_clock", "fixed_range", "tick_bracket"])
class OpeningRangeFailure(OpeningRangeFailureFade):
    """At most the configured number of signals, not one breakout observation.

    Breakouts are observed before range_end + monitor_minutes. A different bar
    must return inside [L,H] with 0 < elapsed <= return_minutes, also strictly
    before that monitoring end. An expired event consumes no signal allowance.
    """
    strategy_id = "opening_range_failure_h02"
    strategy_version = "2"

    def bind_runtime(self, classifier: CalendarClassifier) -> None:
        self.clock = SessionClock(classifier.sessions,
                                  exchange_calendar=classifier.exchange_calendar)

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> Signal | None:
        if bar.session is not Session.DAY:
            return None
        key = (bar.trade_date, bar.session)
        if key != self.current_session:
            self.current_session = key
            self.signals_emitted_in_session = 0
            self.armed_side = self.armed_ts = None
            self.session_diagnostic = None
            start, end = self.clock.opening_window(bar.trade_date, self.opening_minutes)
            self.current_range = FixedRange(start, end)
            self.range_end_ts = end
            self.entry_end_ts = end + timedelta(minutes=self.entry_window_minutes)
        assert self.current_range is not None
        assert self.range_end_ts is not None and self.entry_end_ts is not None
        if bar.ts_jst < self.range_end_ts:
            self.current_range.update(bar.ts_jst, bar.high, bar.low, bar.is_eligible)
            return None
        self.current_range.finalize()
        if not self.current_range.is_tradable:
            self.diagnostics[key] = self.current_range.diagnostic or "range_unavailable"
            return None
        if bar.ts_jst >= self.entry_end_ts:
            self.armed_side = self.armed_ts = None
            return None
        if ctx.has_position or self.signals_emitted_in_session >= self.max_entry_signals_per_session:
            return None
        high, low, width = self.current_range.high, self.current_range.low, self.current_range.width
        assert high is not None and low is not None and width is not None
        if self.armed_side is not None and self.armed_ts is not None:
            elapsed = bar.ts_jst - self.armed_ts
            if elapsed > timedelta(minutes=self.reentry_timeout_minutes):
                self.armed_side = self.armed_ts = None
                # This is already a later bar; it may start a new breakout event.
            elif elapsed > timedelta(0) and low <= bar.close <= high:
                side = self.armed_side
                self.armed_side = self.armed_ts = None
                self.signals_emitted_in_session += 1
                stop = max(1, math.ceil(self.stop_fraction * width / self.tick_size))
                target = max(1, math.ceil(self.reward_multiple * stop))
                stop_price, target_price = tick_bracket(side, bar.close, stop, target, self.tick_size)
                action = SignalAction.ENTER_LONG if side is Side.LONG else SignalAction.ENTER_SHORT
                return Signal(action, bar.ts_jst, stop_price, target_price, "h02_range_reentry_v2")
            else:
                return None
        if bar.close > high + self.breakout_buffer_fraction * width and self.direction in {"short", "both"}:
            self.armed_side, self.armed_ts = Side.SHORT, bar.ts_jst
        elif bar.close < low - self.breakout_buffer_fraction * width and self.direction in {"long", "both"}:
            self.armed_side, self.armed_ts = Side.LONG, bar.ts_jst
        return None


def create_strategy(parameters: dict[str, Any]) -> OpeningRangeFailure:
    """Accept H02 prompt names or the previously generated zero-depth H02 names."""
    values = dict(parameters)
    for public, legacy in {"monitor_minutes": "entry_window_minutes",
                           "breakout_fraction": "breakout_buffer_fraction",
                           "return_minutes": "reentry_timeout_minutes"}.items():
        if public in values:
            if legacy in values and values[legacy] != values[public]:
                raise ValueError(f"conflicting aliases: {public}, {legacy}")
            values[legacy] = values.pop(public)
    if values.get("reentry_depth_fraction", 0) != 0:
        raise ValueError("H02 v2 is a return to [L,H]; nonzero reentry depth is a different hypothesis")
    values["reentry_depth_fraction"] = 0
    return OpeningRangeFailure(**values)
