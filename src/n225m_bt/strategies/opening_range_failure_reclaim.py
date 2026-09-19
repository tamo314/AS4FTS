"""Opening range failure reclaim strategy with session clock and tick brackets."""
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
    id="opening_range_failure_reclaim",
    kind="strategy",
    summary="Opening range failure reclaim: trend-follow only after a breakout returns inside the range and then re-breaks the same threshold",
    tags=["reclaim", "opening_range", "failure", "intraday"],
    uses=["session_clock", "fixed_range", "threshold_cross", "tick_bracket"],
)
class OpeningRangeFailureReclaim:
    """Day-session opening range breakout-return-reclaim strategy with tick brackets.

    After the opening range finalizes, within monitor_minutes it watches for a
    confirmed-bar close that strictly breaks the target-direction threshold
    (H + breakout_buffer_fraction * W for long, L - breakout_buffer_fraction * W
    for short). If a later, distinct confirmed bar returns its close inside
    [L, H] within return_minutes of that breakout, and a still later, distinct
    confirmed bar re-breaks the same threshold in the same direction within
    reclaim_minutes of the return, a trend-following signal fires off that
    reclaim bar's close. A close beyond the opposite threshold cancels the
    pending candidate; either leg timing out clears the candidate without
    spending the session's signal budget and allows rearming on a fresh
    breakout before the monitor deadline.
    """

    strategy_id = "opening_range_failure_reclaim"
    strategy_version = "1"

    def __init__(
        self,
        opening_minutes: int,
        breakout_buffer_fraction: float,
        monitor_minutes: int,
        return_minutes: int,
        reclaim_minutes: int,
        stop_fraction: float,
        reward_multiple: int | float,
        direction: str,
        tick_size: int = 5,
        sessions_path: str = "config/sessions.yaml",
        max_entry_signals_per_session: int = 1,
    ) -> None:
        if direction not in {"long", "short"}:
            raise ValueError(f"direction must be 'long' or 'short', got {direction!r}")
        if min(
            opening_minutes,
            monitor_minutes,
            return_minutes,
            reclaim_minutes,
            tick_size,
            max_entry_signals_per_session,
        ) <= 0:
            raise ValueError(
                "opening_minutes, monitor_minutes, return_minutes, reclaim_minutes, "
                "tick_size, and max_entry_signals_per_session must be positive"
            )
        if stop_fraction <= 0 or reward_multiple <= 0:
            raise ValueError("stop_fraction and reward_multiple must be positive")
        if breakout_buffer_fraction < 0:
            raise ValueError("breakout_buffer_fraction must be non-negative")

        self.opening_minutes = opening_minutes
        self.breakout_buffer_fraction = breakout_buffer_fraction
        self.monitor_minutes = monitor_minutes
        self.return_minutes = return_minutes
        self.reclaim_minutes = reclaim_minutes
        self.stop_fraction = stop_fraction
        self.reward_multiple = reward_multiple
        self.direction = direction
        self.target_side = Side.LONG if direction == "long" else Side.SHORT
        self.tick_size = tick_size
        self.sessions_path = sessions_path
        self.max_entry_signals_per_session = max_entry_signals_per_session

        self.clock = SessionClock(sessions_path)
        self.current_session: tuple[date, Session] | None = None
        self.current_range: FixedRange | None = None
        self.range_end_ts: datetime | None = None
        self.monitor_end_ts: datetime | None = None
        self.signals_emitted_in_session = 0
        self.session_diagnostic: str | None = None
        self.diagnostics: dict[tuple[date, Session], str] = {}

        self.phase = "idle"
        self.breakout_ts: datetime | None = None
        self.return_ts: datetime | None = None

    def _reset_candidate(self) -> None:
        self.phase = "idle"
        self.breakout_ts = None
        self.return_ts = None

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> Signal | None:
        if bar.session is not Session.DAY:
            return None

        session_key = (bar.trade_date, bar.session)
        if session_key != self.current_session:
            self.current_session = session_key
            self.signals_emitted_in_session = 0
            self.session_diagnostic = None
            self._reset_candidate()
            try:
                session_open_ts, range_end_ts = self.clock.opening_window(
                    bar.trade_date, self.opening_minutes, Session.DAY
                )
                self.current_range = FixedRange(session_open_ts, range_end_ts)
                self.range_end_ts = range_end_ts
                self.monitor_end_ts = range_end_ts + timedelta(minutes=self.monitor_minutes)
            except Exception:
                self.current_range = None
                self.range_end_ts = None
                self.monitor_end_ts = None
                self.session_diagnostic = "opening_range_unavailable"
                self.diagnostics[session_key] = self.session_diagnostic
                return None

        if self.current_range is None or self.range_end_ts is None or self.monitor_end_ts is None:
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

        if bar.ts_jst >= self.monitor_end_ts:
            return None

        h = self.current_range.high
        l = self.current_range.low
        w = self.current_range.width
        if h is None or l is None or w is None or w <= 0:
            return None

        upper = h + self.breakout_buffer_fraction * w
        lower = l - self.breakout_buffer_fraction * w
        cross = ThresholdCross(upper=upper, lower=lower)
        if self.target_side is Side.LONG:
            is_target_breakout = cross.is_above(bar.close)
            is_opposite_breakout = cross.is_below(bar.close)
        else:
            is_target_breakout = cross.is_below(bar.close)
            is_opposite_breakout = cross.is_above(bar.close)

        if self.phase == "waiting_return":
            elapsed = bar.ts_jst - self.breakout_ts
            if elapsed > timedelta(minutes=self.return_minutes):
                self._reset_candidate()
            elif is_opposite_breakout:
                self._reset_candidate()
            elif l <= bar.close <= h:
                self.return_ts = bar.ts_jst
                self.phase = "waiting_reclaim"
                return None
            else:
                return None
        elif self.phase == "waiting_reclaim":
            elapsed = bar.ts_jst - self.return_ts
            if elapsed > timedelta(minutes=self.reclaim_minutes):
                self._reset_candidate()
            elif is_opposite_breakout:
                self._reset_candidate()
            elif is_target_breakout:
                self._reset_candidate()
                self.signals_emitted_in_session += 1
                stop_ticks = max(1, math.ceil(self.stop_fraction * w / self.tick_size))
                target_ticks = max(1, math.ceil(self.reward_multiple * stop_ticks))
                stop_price, target_price = tick_bracket(
                    self.target_side, bar.close, stop_ticks, target_ticks, self.tick_size
                )
                action = (
                    SignalAction.ENTER_LONG
                    if self.target_side is Side.LONG
                    else SignalAction.ENTER_SHORT
                )
                return Signal(
                    action=action,
                    timestamp=bar.ts_jst,
                    stop_price=stop_price,
                    target_price=target_price,
                    reason="opening_range_failure_reclaim",
                )
            else:
                return None

        if self.phase == "idle" and is_target_breakout:
            self.breakout_ts = bar.ts_jst
            self.phase = "waiting_return"

        return None


def create_strategy(parameters: dict[str, Any]) -> OpeningRangeFailureReclaim:
    """Create a fresh instance of OpeningRangeFailureReclaim for one parameter set."""
    return OpeningRangeFailureReclaim(**parameters)
