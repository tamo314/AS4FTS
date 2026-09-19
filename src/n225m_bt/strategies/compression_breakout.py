"""Compression breakout strategy composed from session clock, range compression, and tick brackets."""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from n225m_bt.components import component
from n225m_bt.components.event_latch import EventLatch
from n225m_bt.components.primitives import tick_bracket
from n225m_bt.components.range_compression import RangeCompression
from n225m_bt.components.session_clock import SessionClock
from n225m_bt.components.threshold_cross import ThresholdCross
from n225m_bt.domain import Bar, Session, Side, Signal, SignalAction
from n225m_bt.strategies.base import StrategyContext


@component(
    id="compression_breakout",
    kind="strategy",
    summary="Session-local range compression breakout with a fixed candidate latch and tick brackets",
    tags=["breakout", "compression", "intraday"],
    uses=["session_clock", "threshold_cross", "tick_bracket", "range_compression", "event_latch"],
)
class CompressionBreakout:
    """Day-session breakout of a trailing range that has contracted against its recent median.

    Every confirmed bar is folded into a session-local RangeCompression buffer. While
    no candidate is armed, each confirmed bar is tested as a fresh detection instant
    d = ts_jst + 1 minute: if the trailing window R0=[d-w,d) has contracted to at
    most compression_ratio of the median width of the three preceding windows R1,
    R2, R3 (all resolved within the same day session via SessionClock, never from
    the first observed row), R0's high/low/width are frozen into an EventLatch with
    expiry d+w. The bar used for detection never itself enters, since detection only
    runs after that bar's own entry check against any previously armed (and
    strictly older) candidate. While a candidate is armed its range is not re-fitted
    or replaced by a fresh, tighter one. Any later, distinct, eligible confirmed bar
    within (d, d+w] whose close strictly clears H + breakout_buffer_fraction*W
    (long) or L - breakout_buffer_fraction*W (short) fires a signal in the
    configured direction only; opposite-direction breaks neither signal nor cancel
    the candidate, which is otherwise held until expiry. The first bar confirmed
    after d+w invalidates the candidate before any breakout check, though that same
    bar may still seed a new candidate (but cannot itself enter on it). At most
    max_entry_signals_per_session signals are emitted per session, and the budget is
    spent at signal time regardless of whether the resulting order later fills.
    """

    strategy_id = "compression_breakout"
    strategy_version = "1"

    def __init__(
        self,
        window_minutes: int,
        compression_ratio: float,
        breakout_buffer_fraction: float,
        stop_fraction: float,
        reward_multiple: int | float,
        direction: str,
        tick_size: int = 5,
        sessions_path: str = "config/sessions.yaml",
        max_entry_signals_per_session: int = 1,
    ) -> None:
        if direction not in {"long", "short"}:
            raise ValueError(f"direction must be 'long' or 'short', got {direction!r}")
        if window_minutes <= 0:
            raise ValueError("window_minutes must be positive")
        if not (0 < compression_ratio < 1):
            raise ValueError("compression_ratio must be strictly between 0 and 1")
        if breakout_buffer_fraction < 0:
            raise ValueError("breakout_buffer_fraction must be non-negative")
        if stop_fraction <= 0 or reward_multiple <= 0:
            raise ValueError("stop_fraction and reward_multiple must be positive")
        if tick_size <= 0 or max_entry_signals_per_session <= 0:
            raise ValueError("tick_size and max_entry_signals_per_session must be positive")

        self.window_minutes = window_minutes
        self.compression_ratio = compression_ratio
        self.breakout_buffer_fraction = breakout_buffer_fraction
        self.stop_fraction = stop_fraction
        self.reward_multiple = reward_multiple
        self.direction = direction
        self.tick_size = tick_size
        self.sessions_path = sessions_path
        self.max_entry_signals_per_session = max_entry_signals_per_session

        self.clock = SessionClock(sessions_path)
        self.current_session: tuple[date, Session] | None = None
        self.session_ok = False
        self.range_compression = RangeCompression()
        self.latch = EventLatch()
        self.signals_emitted_in_session = 0

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> Signal | None:
        if bar.session is not Session.DAY:
            return None

        session_key = (bar.trade_date, bar.session)
        if session_key != self.current_session:
            self.current_session = session_key
            self.signals_emitted_in_session = 0
            self.range_compression = RangeCompression()
            self.latch = EventLatch()
            try:
                session_open_ts = self.clock.session_open(bar.trade_date, Session.DAY)
                self.range_compression.reset(session_open_ts)
                self.session_ok = True
            except Exception:
                self.session_ok = False

        if not self.session_ok:
            return None

        d_now = bar.ts_jst + timedelta(minutes=1)
        signal: Signal | None = None

        if self.latch.is_armed:
            if d_now > self.latch.expires_at:
                self.latch.expire_if_due(d_now)
            elif (
                bar.is_eligible
                and not ctx.has_position
                and self.signals_emitted_in_session < self.max_entry_signals_per_session
            ):
                candidate = self.latch.payload
                upper = candidate.high + self.breakout_buffer_fraction * candidate.width
                lower = candidate.low - self.breakout_buffer_fraction * candidate.width
                cross = ThresholdCross(upper=upper, lower=lower)
                side = cross.classify(bar.close, self.direction)
                if side is not None:
                    self.signals_emitted_in_session += 1
                    stop_ticks = max(1, math.ceil(self.stop_fraction * candidate.width / self.tick_size))
                    target_ticks = max(1, math.ceil(self.reward_multiple * stop_ticks))
                    stop_price, target_price = tick_bracket(
                        side, bar.close, stop_ticks, target_ticks, self.tick_size
                    )
                    action = SignalAction.ENTER_LONG if side is Side.LONG else SignalAction.ENTER_SHORT
                    signal = Signal(
                        action=action,
                        timestamp=bar.ts_jst,
                        stop_price=stop_price,
                        target_price=target_price,
                        reason="compression_breakout",
                    )

        self.range_compression.update(bar.ts_jst, bar.high, bar.low, bar.is_eligible)

        if not self.latch.is_armed:
            candidate = self.range_compression.evaluate(
                d_now, self.window_minutes, self.compression_ratio
            )
            if candidate is not None:
                self.latch.set(
                    candidate,
                    detected_at=d_now,
                    expires_at=d_now + timedelta(minutes=self.window_minutes),
                )

        return signal


def create_strategy(parameters: dict[str, Any]) -> CompressionBreakout:
    """Create a fresh instance of CompressionBreakout for one parameter set."""
    return CompressionBreakout(**parameters)
