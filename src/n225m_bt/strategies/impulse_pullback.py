"""Impulse-pullback strategy composed from session clock, directional efficiency, and tick brackets."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from n225m_bt.components import component
from n225m_bt.components.directional_efficiency import DirectionalEfficiency
from n225m_bt.components.event_latch import EventLatch
from n225m_bt.components.primitives import tick_bracket
from n225m_bt.components.session_clock import SessionClock
from n225m_bt.domain import Bar, Session, Side, Signal, SignalAction
from n225m_bt.strategies.base import StrategyContext

_PULLBACK_PROFILES: dict[str, tuple[float, float]] = {
    "shallow": (0.25, 0.50),
    "deep": (0.50, 0.75),
}


@dataclass(frozen=True, slots=True)
class _ImpulseCandidate:
    p: int
    width: int


@component(
    id="impulse_pullback",
    kind="strategy",
    summary="Waits for a pullback and a separate-bar resume confirmation after a directionally efficient impulse",
    tags=["pullback", "impulse", "efficiency", "intraday"],
    uses=["session_clock", "event_latch", "tick_bracket", "directional_efficiency"],
)
class ImpulsePullback:
    """Day-session impulse-pullback-resume strategy with tick brackets.

    Every confirmed bar is folded into a session-local DirectionalEfficiency buffer.
    While no candidate is held, each confirmed bar is tested as a fresh detection
    instant d = ts_jst + 1 minute: if the window [d-w, d] has directional efficiency
    E >= min_efficiency, its close-to-close width W is at least the median width M
    of the three preceding, non-overlapping windows, and the impulse's sign matches
    direction, the impulse endpoint P = close of the detecting bar and W are frozen
    into an EventLatch with expiry d+w. The detecting bar itself never acts on the
    candidate it just created. While a candidate is held its P and W are never
    re-fitted or replaced by a fresh candidate. The confirmation bar at the expiry
    endpoint d+w is valid; the first bar whose confirmation instant strictly exceeds
    the deadline releases the candidate before any action check on that bar, though
    that same bar may still seed a brand-new candidate (but cannot itself enter on
    it).

    While a candidate is held, each eligible confirmed bar computes the pullback
    fraction from P ((P-close)/W for long, (close-P)/W for short). If that fraction
    strictly exceeds the pullback profile's upper bound, the candidate is released
    before any resume check. The first confirmed bar whose fraction falls within
    the profile's closed [min, max] band is recorded, but that bar can never itself
    be the resume bar. Only a later, distinct, eligible confirmed bar whose close
    strictly clears the immediately preceding eligible confirmed bar's high (long)
    or low (short) fires the resume signal. At most max_entry_signals_per_session
    signals are emitted per session, and the budget is spent at signal time
    regardless of whether the resulting order later fills.
    """

    strategy_id = "impulse_pullback"
    strategy_version = "1"

    def __init__(
        self,
        window_minutes: int,
        min_efficiency: float,
        pullback_profile: str,
        stop_fraction: float,
        reward_multiple: int | float,
        direction: str,
        tick_size: int = 5,
        sessions_path: str = "config/sessions.yaml",
        max_entry_signals_per_session: int = 1,
    ) -> None:
        if direction not in {"long", "short"}:
            raise ValueError(f"direction must be 'long' or 'short', got {direction!r}")
        if pullback_profile not in _PULLBACK_PROFILES:
            raise ValueError(f"pullback_profile must be 'shallow' or 'deep', got {pullback_profile!r}")
        if window_minutes <= 0:
            raise ValueError("window_minutes must be positive")
        if not (0 < min_efficiency <= 1):
            raise ValueError("min_efficiency must be strictly between 0 and 1")
        if stop_fraction <= 0 or reward_multiple <= 0:
            raise ValueError("stop_fraction and reward_multiple must be positive")
        if tick_size <= 0 or max_entry_signals_per_session <= 0:
            raise ValueError("tick_size and max_entry_signals_per_session must be positive")

        self.window_minutes = window_minutes
        self.min_efficiency = min_efficiency
        self.pullback_profile = pullback_profile
        self.pullback_min_fraction, self.pullback_max_fraction = _PULLBACK_PROFILES[pullback_profile]
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
        self.efficiency = DirectionalEfficiency()
        self.latch = EventLatch()
        self.sub_phase: str | None = None  # None | "await_band" | "await_resume"
        self.previous_valid_bar: Bar | None = None
        self.signals_emitted_in_session = 0

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> Signal | None:
        if bar.session is not Session.DAY:
            return None

        session_key = (bar.trade_date, bar.session)
        if session_key != self.current_session:
            self.current_session = session_key
            self.signals_emitted_in_session = 0
            self.efficiency = DirectionalEfficiency()
            self.latch = EventLatch()
            self.sub_phase = None
            self.previous_valid_bar = None
            try:
                session_open_ts = self.clock.session_open(bar.trade_date, Session.DAY)
                self.efficiency.reset(session_open_ts)
                self.session_ok = True
            except Exception:
                self.session_ok = False

        if not self.session_ok:
            return None

        d_now = bar.ts_jst + timedelta(minutes=1)
        signal: Signal | None = None

        if self.latch.is_armed and self.latch.expire_if_due(d_now):
            self.sub_phase = None

        if (
            self.latch.is_armed
            and bar.is_eligible
            and not ctx.has_position
            and self.signals_emitted_in_session < self.max_entry_signals_per_session
        ):
            candidate = self.latch.payload
            if self.side is Side.LONG:
                pullback_fraction = (candidate.p - bar.close) / candidate.width
            else:
                pullback_fraction = (bar.close - candidate.p) / candidate.width

            if pullback_fraction > self.pullback_max_fraction:
                self.latch.consume()
                self.sub_phase = None
            elif self.sub_phase == "await_resume":
                prev = self.previous_valid_bar
                if prev is not None:
                    if self.side is Side.LONG:
                        resumed = bar.close > prev.high
                    else:
                        resumed = bar.close < prev.low
                    if resumed:
                        self.latch.consume()
                        self.sub_phase = None
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
                            reason="impulse_pullback",
                        )
            elif self.sub_phase in (None, "await_band"):
                if self.pullback_min_fraction <= pullback_fraction <= self.pullback_max_fraction:
                    self.sub_phase = "await_resume"

        self.efficiency.update(bar.ts_jst, bar.high, bar.low, bar.close, bar.is_eligible)

        if not self.latch.is_armed:
            result = self.efficiency.evaluate(d_now, self.window_minutes)
            if (
                result is not None
                and result.efficiency >= self.min_efficiency
                and result.width >= result.prior_range_median
                and (result.impulse > 0) == (self.side is Side.LONG)
            ):
                self.latch.set(
                    _ImpulseCandidate(p=bar.close, width=result.width),
                    detected_at=d_now,
                    expires_at=d_now + timedelta(minutes=self.window_minutes),
                )
                self.sub_phase = "await_band"

        if bar.is_eligible:
            self.previous_valid_bar = bar

        return signal


def create_strategy(parameters: dict[str, Any]) -> ImpulsePullback:
    """Create a fresh instance of ImpulsePullback for one parameter set."""
    return ImpulsePullback(**parameters)
