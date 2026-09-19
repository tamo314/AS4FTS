"""Pre-close confirmed reversal adapter over session clock/OHLC, an event latch, and threshold cross."""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from n225m_bt.calendar.classifier import CalendarClassifier
from n225m_bt.components import component
from n225m_bt.components.event_latch import EventLatch
from n225m_bt.components.primitives import tick_bracket
from n225m_bt.components.session_clock import SessionClock
from n225m_bt.components.session_ohlc import SessionOHLC
from n225m_bt.components.threshold_cross import ThresholdCross
from n225m_bt.domain import Bar, Session, Side, Signal, SignalAction
from n225m_bt.strategies.base import StrategyContext


@component(
    id="preclose_confirmed_reversal",
    kind="strategy",
    summary="Waits for a confirmed close-back reversal against a directionally decisive pre-close move",
    tags=["preclose", "session", "reversal", "confirmation", "intraday"],
    uses=["session_clock", "session_ohlc", "event_latch", "threshold_cross", "tick_bracket"],
)
class PrecloseConfirmedReversal:
    """Day-session reversal off the move from the day open to a pre-close decision instant, entered
    only once a later bar confirms the reversal by closing back through a fraction of the day's range.

    Every trade_date resets on its first DAY bar. The official day open/close instants
    come from SessionClock, never guessed from the first observed row. The decision
    instant D = session_close - minutes_before_close is a wall-clock instant; because
    bars are keyed by their own start timestamp and confirm one minute later, the bar
    that confirms exactly at D has ts_jst = D - 1 minute ("the decision bar"). Only
    that exact bar, observed and eligible, is ever used to decide; a later bar is
    never substituted for a missing or ineligible decision bar.

    Day open price Od is defined only from a bar whose ts_jst exactly equals the
    official session_open and which is eligible; if that exact bar is missing or not
    eligible, Od is never defined and the trade_date is skipped. Only bars observed
    within the closed window [session_open, decision_bar_ts] are folded into a
    SessionOHLC (missing bars are never imputed); its finalized close is Ct and its
    finalized high/low give W = H - L. If the decision instant does not fall strictly
    after session_open, the decision bar is missing or ineligible, W is not strictly
    positive, or Ct equals Od, the trade_date is skipped with no candidate.

    day_direction = abs(Ct - Od) / W must be at least min_day_direction. The candidate
    direction is the reversal of the day's move, sign(Od - Ct); a candidate is only
    armed when this equals the configured direction. Ct, W, and the confirmation
    threshold (Ct + confirmation_fraction*W for long, Ct - confirmation_fraction*W
    for short) are frozen into an EventLatch valid over [D, D + confirmation_window_
    minutes]; the decision bar itself is never used to confirm its own candidate.

    While the candidate is held, each later, distinct, eligible confirmed bar's close
    is tested with a strict ThresholdCross against the frozen threshold. The deadline
    endpoint is valid; the first bar whose confirmation instant (ts_jst + 1 minute)
    strictly exceeds the deadline releases the candidate before any confirmation
    check on that same bar. The confirming bar's own close (never the decision bar's
    Ct and never an unknown future fill) is the tick_bracket reference. Confirmation
    is a single-use event: once detected the candidate is consumed regardless of
    whether a signal is actually emitted. Candidate arming alone never spends the
    session's signal budget; only an emitted confirmation signal does, and an
    existing open position suppresses the signal without returning the budget. At
    most max_entry_signals_per_session signals are emitted per trade_date, and
    candidates never carry over to the next trade_date.
    """

    strategy_id = "preclose_confirmed_reversal"
    strategy_version = "1"

    def __init__(
        self,
        confirmation_fraction: float,
        confirmation_window_minutes: int,
        direction: str,
        min_day_direction: float,
        minutes_before_close: int,
        reward_multiple: int | float,
        stop_fraction: float,
        tick_size: int = 5,
        sessions_path: str = "config/sessions.yaml",
        max_entry_signals_per_session: int = 1,
    ) -> None:
        if direction not in {"long", "short"}:
            raise ValueError(f"direction must be 'long' or 'short', got {direction!r}")
        if minutes_before_close <= 0:
            raise ValueError("minutes_before_close must be positive")
        if confirmation_window_minutes <= 0:
            raise ValueError("confirmation_window_minutes must be positive")
        if confirmation_fraction <= 0:
            raise ValueError("confirmation_fraction must be positive")
        if not (0 <= min_day_direction <= 1):
            raise ValueError("min_day_direction must be between 0 and 1")
        if stop_fraction <= 0 or reward_multiple <= 0:
            raise ValueError("stop_fraction and reward_multiple must be positive")
        if tick_size <= 0 or max_entry_signals_per_session <= 0:
            raise ValueError("tick_size and max_entry_signals_per_session must be positive")

        self.confirmation_fraction = confirmation_fraction
        self.confirmation_window_minutes = confirmation_window_minutes
        self.direction = direction
        self.direction_sign = 1 if direction == "long" else -1
        self.side = Side.LONG if direction == "long" else Side.SHORT
        self.min_day_direction = min_day_direction
        self.minutes_before_close = minutes_before_close
        self.reward_multiple = reward_multiple
        self.stop_fraction = stop_fraction
        self.tick_size = tick_size
        self.sessions_path = sessions_path
        self.max_entry_signals_per_session = max_entry_signals_per_session

        self.clock = SessionClock(sessions_path)
        self.latch = EventLatch()
        self.current_trade_date: date | None = None
        self.day_open_ts = None
        self.decision_ts = None
        self.decision_bar_ts = None
        self.expiry_ts = None
        self.ohlc: SessionOHLC | None = None
        self.open_price: int | None = None
        # phase: collecting | watching | resolved
        self.phase = "resolved"
        self.signals_emitted = 0

    def bind_runtime(self, classifier: CalendarClassifier) -> None:
        """Bind the same versioned sessions and calendar used by the execution engine."""
        self.clock = SessionClock(
            classifier.sessions, exchange_calendar=classifier.exchange_calendar,
        )

    def _reset_for_trade_date(self, trade_date: date) -> None:
        self.current_trade_date = trade_date
        self.signals_emitted = 0
        self.open_price = None
        self.latch.consume()
        day_open_ts = self.clock.session_open(trade_date, Session.DAY)
        day_close_ts = self.clock.session_close(trade_date, Session.DAY)
        decision_ts = day_close_ts - timedelta(minutes=self.minutes_before_close)
        decision_bar_ts = decision_ts - timedelta(minutes=1)
        self.day_open_ts = day_open_ts
        self.decision_ts = decision_ts
        self.decision_bar_ts = decision_bar_ts
        self.expiry_ts = decision_ts + timedelta(minutes=self.confirmation_window_minutes)
        if decision_bar_ts <= day_open_ts:
            # The decision instant does not fall strictly after the open, so no
            # aggregation window exists; hold this as an invalidated, no-trade
            # outcome rather than constructing an empty/invalid window.
            self.ohlc = None
            self.phase = "resolved"
            return
        self.ohlc = SessionOHLC(day_open_ts, decision_bar_ts)
        self.phase = "collecting"

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> Signal | None:
        if bar.session is not Session.DAY:
            return None

        if bar.trade_date != self.current_trade_date:
            self._reset_for_trade_date(bar.trade_date)

        if self.phase == "resolved":
            return None
        if self.phase == "watching":
            return self._handle_watching(ctx, bar)
        return self._handle_collecting(bar)

    def _handle_collecting(self, bar: Bar) -> Signal | None:
        assert self.ohlc is not None and self.day_open_ts is not None
        assert self.decision_bar_ts is not None and self.decision_ts is not None

        if bar.ts_jst == self.day_open_ts:
            if not bar.is_eligible:
                self.phase = "resolved"
                return None
            self.open_price = bar.open

        if bar.ts_jst > self.decision_bar_ts:
            # The decision bar never confirmed exactly at the decision instant;
            # a later bar is never substituted for it.
            self.phase = "resolved"
            return None

        is_decision_bar = bar.ts_jst == self.decision_bar_ts
        if is_decision_bar and not bar.is_eligible:
            self.phase = "resolved"
            return None

        self.ohlc.update(bar.ts_jst, bar.open, bar.high, bar.low, bar.close, bar.is_eligible)

        if not is_decision_bar:
            return None

        # This is the decision bar's exact confirmation; evaluate the candidate once.
        self.ohlc.finalize()
        if self.open_price is None or not self.ohlc.is_tradable:
            self.phase = "resolved"
            return None

        od = self.open_price
        ct = self.ohlc.close
        hi = self.ohlc.high
        lo = self.ohlc.low
        if ct is None or hi is None or lo is None:
            self.phase = "resolved"
            return None
        width = hi - lo
        if width <= 0 or ct == od:
            self.phase = "resolved"
            return None

        day_direction = abs(ct - od) / width
        if day_direction < self.min_day_direction:
            self.phase = "resolved"
            return None

        day_move_sign = 1 if ct > od else -1
        candidate_sign = -day_move_sign
        if candidate_sign != self.direction_sign:
            self.phase = "resolved"
            return None

        offset = self.confirmation_fraction * width
        if self.direction == "long":
            cross = ThresholdCross(upper=ct + offset)
        else:
            cross = ThresholdCross(lower=ct - offset)
        self.latch.set(
            {"width": width, "cross": cross},
            detected_at=self.decision_ts,
            expires_at=self.expiry_ts,
        )
        self.phase = "watching"
        return None

    def _handle_watching(self, ctx: StrategyContext, bar: Bar) -> Signal | None:
        confirm_instant = bar.ts_jst + timedelta(minutes=1)
        just_expired = self.latch.expire_if_due(confirm_instant)
        if just_expired or not self.latch.is_armed:
            self.phase = "resolved"
            return None

        if not bar.is_eligible:
            return None

        payload = self.latch.payload
        cross: ThresholdCross = payload["cross"]
        width: int = payload["width"]

        confirmed = cross.is_above(bar.close) if self.direction == "long" else cross.is_below(bar.close)
        if not confirmed:
            return None

        # Confirmation is a single-use event: the candidate is consumed here
        # whether or not a signal is actually emitted below.
        self.latch.consume()
        self.phase = "resolved"

        if self.signals_emitted >= self.max_entry_signals_per_session:
            return None
        if ctx.has_position:
            return None

        self.signals_emitted += 1
        stop_ticks = max(1, math.ceil(self.stop_fraction * width / self.tick_size))
        target_ticks = max(1, math.ceil(self.reward_multiple * stop_ticks))
        stop_price, target_price = tick_bracket(
            self.side, bar.close, stop_ticks, target_ticks, self.tick_size
        )
        action = SignalAction.ENTER_LONG if self.side is Side.LONG else SignalAction.ENTER_SHORT
        return Signal(
            action=action,
            timestamp=bar.ts_jst,
            stop_price=stop_price,
            target_price=target_price,
            reason="preclose_confirmed_reversal",
        )


def create_strategy(parameters: dict[str, Any]) -> PrecloseConfirmedReversal:
    """Create a fresh instance of PrecloseConfirmedReversal for one parameter set."""
    return PrecloseConfirmedReversal(**parameters)
