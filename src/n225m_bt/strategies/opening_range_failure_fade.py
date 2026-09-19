"""Opening range failure fade strategy with session clock and tick brackets."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

from n225m_bt.components import component
from n225m_bt.components.fixed_range import FixedRange
from n225m_bt.components.primitives import tick_bracket
from n225m_bt.components.session_clock import SessionClock
from n225m_bt.components.threshold_cross import ThresholdCross
from n225m_bt.domain import Bar, Session, Side, Signal, SignalAction
from n225m_bt.strategies.base import StrategyContext


@component(
    id="opening_range_failure_fade",
    kind="strategy",
    summary="Opening range failure fade with session clock, fixed range, strict threshold cross and tick bracket",
    tags=["fade", "opening_range", "failure", "intraday"],
    uses=["session_clock", "fixed_range", "threshold_cross", "tick_bracket"],
)
class OpeningRangeFailureFade:
    """Day-session opening range failure fade strategy with tick brackets."""

    strategy_id = "opening_range_failure_fade"
    strategy_version = "1"

    def __init__(
        self,
        opening_minutes: int,
        breakout_buffer_fraction: float,
        entry_window_minutes: int,
        reentry_depth_fraction: float,
        reentry_timeout_minutes: int,
        stop_fraction: float,
        reward_multiple: int | float,
        direction: str = "both",
        tick_size: int = 5,
        sessions_path: str = "config/sessions.yaml",
        max_entry_signals_per_session: int = 1,
    ) -> None:
        if direction not in {"long", "short", "both"}:
            raise ValueError(f"direction must be 'long', 'short', or 'both', got {direction!r}")
        if min(
            opening_minutes,
            entry_window_minutes,
            reentry_timeout_minutes,
            tick_size,
            max_entry_signals_per_session,
        ) <= 0:
            raise ValueError(
                "opening_minutes, entry_window_minutes, reentry_timeout_minutes, tick_size, and max_entry_signals_per_session must be positive"
            )
        if stop_fraction <= 0 or reward_multiple <= 0:
            raise ValueError("stop_fraction and reward_multiple must be positive")
        if breakout_buffer_fraction < 0 or reentry_depth_fraction < 0:
            raise ValueError("breakout_buffer_fraction and reentry_depth_fraction must be non-negative")

        self.opening_minutes = opening_minutes
        self.breakout_buffer_fraction = breakout_buffer_fraction
        self.entry_window_minutes = entry_window_minutes
        self.reentry_depth_fraction = reentry_depth_fraction
        self.reentry_timeout_minutes = reentry_timeout_minutes
        self.stop_fraction = stop_fraction
        self.reward_multiple = reward_multiple
        self.direction = direction
        self.tick_size = tick_size
        self.sessions_path = sessions_path
        self.max_entry_signals_per_session = max_entry_signals_per_session

        self.clock = SessionClock(sessions_path)
        self.current_session: tuple[date, Session] | None = None
        self.current_range: FixedRange | None = None
        self.range_end_ts: datetime | None = None
        self.entry_end_ts: datetime | None = None
        self.arm_end_ts: datetime | None = None
        self.signals_emitted_in_session = 0
        self.session_diagnostic: str | None = None
        self.diagnostics: dict[tuple[date, Session], str] = {}

        self.armed_side: Side | None = None
        self.armed_ts: datetime | None = None
        self.has_armed_in_session = False

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> Signal | None:
        if bar.session is not Session.DAY:
            return None

        session_key = (bar.trade_date, bar.session)
        if session_key != self.current_session:
            self.current_session = session_key
            self.signals_emitted_in_session = 0
            self.session_diagnostic = None
            self.armed_side = None
            self.armed_ts = None
            self.has_armed_in_session = False
            try:
                session_open_ts, range_end_ts = self.clock.opening_window(
                    bar.trade_date, self.opening_minutes, Session.DAY
                )
                self.current_range = FixedRange(session_open_ts, range_end_ts)
                self.range_end_ts = range_end_ts
                self.entry_end_ts = range_end_ts + timedelta(minutes=self.entry_window_minutes)
                self.arm_end_ts = self.entry_end_ts - timedelta(minutes=self.reentry_timeout_minutes)
            except Exception:
                self.current_range = None
                self.range_end_ts = None
                self.entry_end_ts = None
                self.arm_end_ts = None
                self.session_diagnostic = "opening_range_unavailable"
                self.diagnostics[session_key] = self.session_diagnostic
                return None

        if (
            self.current_range is None
            or self.range_end_ts is None
            or self.entry_end_ts is None
            or self.arm_end_ts is None
        ):
            return None

        if bar.ts_jst < self.range_end_ts:
            self.current_range.update(bar.ts_jst, bar.high, bar.low, bar.is_eligible)
            if not self.current_range.is_available:
                self.session_diagnostic = self.current_range.diagnostic
                self.diagnostics[session_key] = self.session_diagnostic
            return None

        if not self.current_range.is_finalized:
            self.current_range.finalize()
            if not self.current_range.is_available:
                self.session_diagnostic = self.current_range.diagnostic
                self.diagnostics[session_key] = self.session_diagnostic

        if not self.current_range.is_tradable:
            return None

        if self.signals_emitted_in_session >= self.max_entry_signals_per_session:
            return None

        if ctx.has_position:
            return None

        h = self.current_range.high
        l = self.current_range.low
        w = self.current_range.width
        if h is None or l is None or w is None or w <= 0:
            return None

        if not self.has_armed_in_session:
            if bar.ts_jst < self.arm_end_ts:
                upper = h + self.breakout_buffer_fraction * w
                lower = l - self.breakout_buffer_fraction * w
                cross = ThresholdCross(upper=upper, lower=lower)
                if self.direction in {"short", "both"} and cross.is_above(bar.close):
                    self.has_armed_in_session = True
                    self.armed_side = Side.SHORT
                    self.armed_ts = bar.ts_jst
                    return None
                elif self.direction in {"long", "both"} and cross.is_below(bar.close):
                    self.has_armed_in_session = True
                    self.armed_side = Side.LONG
                    self.armed_ts = bar.ts_jst
                    return None
            return None

        if self.armed_side is not None and self.armed_ts is not None:
            timeout_ts = self.armed_ts + timedelta(minutes=self.reentry_timeout_minutes)
            if bar.ts_jst >= timeout_ts:
                self.armed_side = None
                return None

            if self.armed_side is Side.SHORT:
                reentry_threshold = h - self.reentry_depth_fraction * w
                cross = ThresholdCross(lower=reentry_threshold)
                if cross.is_below(bar.close):
                    self.armed_side = None
                    self.signals_emitted_in_session += 1
                    stop_ticks = max(1, math.ceil(self.stop_fraction * w / self.tick_size))
                    target_ticks = max(1, math.ceil(self.reward_multiple * stop_ticks))
                    stop_price, target_price = tick_bracket(
                        Side.SHORT, bar.close, stop_ticks, target_ticks, self.tick_size
                    )
                    return Signal(
                        action=SignalAction.ENTER_SHORT,
                        timestamp=bar.ts_jst,
                        stop_price=stop_price,
                        target_price=target_price,
                        reason="opening_range_failure_fade",
                    )
            elif self.armed_side is Side.LONG:
                reentry_threshold = l + self.reentry_depth_fraction * w
                cross = ThresholdCross(upper=reentry_threshold)
                if cross.is_above(bar.close):
                    self.armed_side = None
                    self.signals_emitted_in_session += 1
                    stop_ticks = max(1, math.ceil(self.stop_fraction * w / self.tick_size))
                    target_ticks = max(1, math.ceil(self.reward_multiple * stop_ticks))
                    stop_price, target_price = tick_bracket(
                        Side.LONG, bar.close, stop_ticks, target_ticks, self.tick_size
                    )
                    return Signal(
                        action=SignalAction.ENTER_LONG,
                        timestamp=bar.ts_jst,
                        stop_price=stop_price,
                        target_price=target_price,
                        reason="opening_range_failure_fade",
                    )

        return None


def create_strategy(parameters: dict[str, Any]) -> OpeningRangeFailureFade:
    """Create a fresh instance of OpeningRangeFailureFade for one parameter set."""
    return OpeningRangeFailureFade(**parameters)
