"""Compression failure fade strategy composed from session clock, range compression, and tick brackets."""
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
    id="compression_failure_fade",
    kind="strategy",
    summary="Fades a failed outward break of a session-local compressed range back toward the range",
    tags=["fade", "compression", "failure", "intraday"],
    uses=["session_clock", "range_compression", "event_latch", "threshold_cross", "tick_bracket"],
)
class CompressionFailureFade:
    """Day-session fade of a failed outward break from a trailing compressed range.

    Every confirmed bar is folded into a session-local RangeCompression buffer, updated
    the same way as the compression_breakout family. While no candidate is held, each
    confirmed bar is tested as a fresh detection instant d = ts_jst + 1 minute: if the
    trailing window R0=[d-w,d) has contracted to at most compression_ratio of the
    median width of the three preceding, non-overlapping windows R1, R2, R3 (all
    resolved within the same day session via SessionClock), R0's high/low/width are
    frozen into an EventLatch keyed by the detection instant d and an expiry of d+w.
    The detecting bar itself never acts on the candidate it just created, since
    detection is only evaluated after this bar's own check against any previously
    held candidate. While a candidate is held its H/L/W are never re-fitted or
    replaced by a fresh, tighter one, even after an outward breakout is observed.

    While watching for the outward breakout (armed at d, expiring at d+w), any later,
    distinct, eligible confirmed bar whose close strictly clears L - buffer*W (long)
    or H + buffer*W (short) fixes that bar's confirmation instant as the failure
    candidate's outward breakout, and the held candidate is re-armed with the same
    frozen H/L/W but a new expiry of breakout_ts + reentry_timeout_minutes. Only a
    later, distinct, eligible confirmed bar within that reentry window whose close
    strictly clears L + reentry_depth_fraction*W (long) or H - reentry_depth_fraction*W
    (short) fires the reverse (fade) signal. Endpoint confirmation instants are valid;
    the first bar whose confirmation instant strictly exceeds the current deadline
    releases the candidate before any action check on that bar, though that same bar
    may still seed a brand-new compression candidate. The initial outward breakout
    alone never spends the session's signal budget; only the reentry fade signal does,
    and the budget is not returned if the resulting order later fails to fill. At most
    max_entry_signals_per_session signals are emitted per session.
    """

    strategy_id = "compression_failure_fade"
    strategy_version = "1"

    def __init__(
        self,
        window_minutes: int,
        compression_ratio: float,
        breakout_buffer_fraction: float,
        reentry_depth_fraction: float,
        reentry_timeout_minutes: int,
        stop_fraction: float,
        reward_multiple: int | float,
        direction: str,
        tick_size: int = 5,
        sessions_path: str = "config/sessions.yaml",
        max_entry_signals_per_session: int = 1,
    ) -> None:
        if direction not in {"long", "short"}:
            raise ValueError(f"direction must be 'long' or 'short', got {direction!r}")
        if window_minutes <= 0 or reentry_timeout_minutes <= 0:
            raise ValueError("window_minutes and reentry_timeout_minutes must be positive")
        if not (0 < compression_ratio < 1):
            raise ValueError("compression_ratio must be strictly between 0 and 1")
        if breakout_buffer_fraction < 0 or reentry_depth_fraction < 0:
            raise ValueError("breakout_buffer_fraction and reentry_depth_fraction must be non-negative")
        if stop_fraction <= 0 or reward_multiple <= 0:
            raise ValueError("stop_fraction and reward_multiple must be positive")
        if tick_size <= 0 or max_entry_signals_per_session <= 0:
            raise ValueError("tick_size and max_entry_signals_per_session must be positive")

        self.window_minutes = window_minutes
        self.compression_ratio = compression_ratio
        self.breakout_buffer_fraction = breakout_buffer_fraction
        self.reentry_depth_fraction = reentry_depth_fraction
        self.reentry_timeout_minutes = reentry_timeout_minutes
        self.stop_fraction = stop_fraction
        self.reward_multiple = reward_multiple
        self.direction = direction
        self.side = Side.LONG if direction == "long" else Side.SHORT
        self.tick_size = tick_size
        self.sessions_path = sessions_path
        self.max_entry_signals_per_session = max_entry_signals_per_session

        self.clock = SessionClock(sessions_path)
        self.current_session: tuple[date, Session] | None = None
        self.session_ok = False
        self.range_compression = RangeCompression()
        self.latch = EventLatch()
        self.phase: str | None = None  # None | "breakout_watch" | "reentry_watch"
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
            self.phase = None
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
                self.phase = None
            elif (
                bar.is_eligible
                and not ctx.has_position
                and self.signals_emitted_in_session < self.max_entry_signals_per_session
            ):
                candidate = self.latch.payload
                if self.phase == "breakout_watch":
                    if self.direction == "long":
                        lower = candidate.low - self.breakout_buffer_fraction * candidate.width
                        breached = ThresholdCross(lower=lower).is_below(bar.close)
                    else:
                        upper = candidate.high + self.breakout_buffer_fraction * candidate.width
                        breached = ThresholdCross(upper=upper).is_above(bar.close)
                    if breached:
                        self.latch.set(
                            candidate,
                            detected_at=d_now,
                            expires_at=d_now + timedelta(minutes=self.reentry_timeout_minutes),
                        )
                        self.phase = "reentry_watch"
                elif self.phase == "reentry_watch":
                    if self.direction == "long":
                        upper = candidate.low + self.reentry_depth_fraction * candidate.width
                        reentered = ThresholdCross(upper=upper).is_above(bar.close)
                    else:
                        lower = candidate.high - self.reentry_depth_fraction * candidate.width
                        reentered = ThresholdCross(lower=lower).is_below(bar.close)
                    if reentered:
                        self.latch.consume()
                        self.phase = None
                        self.signals_emitted_in_session += 1
                        stop_ticks = max(1, math.ceil(self.stop_fraction * candidate.width / self.tick_size))
                        target_ticks = max(1, math.ceil(self.reward_multiple * stop_ticks))
                        stop_price, target_price = tick_bracket(
                            self.side, bar.close, stop_ticks, target_ticks, self.tick_size
                        )
                        action = (
                            SignalAction.ENTER_LONG if self.side is Side.LONG else SignalAction.ENTER_SHORT
                        )
                        signal = Signal(
                            action=action,
                            timestamp=bar.ts_jst,
                            stop_price=stop_price,
                            target_price=target_price,
                            reason="compression_failure_fade",
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
                self.phase = "breakout_watch"

        return signal


def create_strategy(parameters: dict[str, Any]) -> CompressionFailureFade:
    """Create a fresh instance of CompressionFailureFade for one parameter set."""
    return CompressionFailureFade(**parameters)
