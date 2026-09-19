"""Pre-close directional response adapter over session clock, session OHLC, and tick brackets."""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from n225m_bt.calendar.classifier import CalendarClassifier
from n225m_bt.components import component
from n225m_bt.components.primitives import tick_bracket
from n225m_bt.components.session_clock import SessionClock
from n225m_bt.components.session_ohlc import SessionOHLC
from n225m_bt.domain import Bar, Session, Side, Signal, SignalAction
from n225m_bt.strategies.base import StrategyContext


@component(
    id="preclose_response",
    kind="strategy",
    summary="Trades the day-session pre-close continuation or reversal of the intraday move from the open",
    tags=["preclose", "session", "continuation", "reversal", "intraday"],
    uses=["session_clock", "session_ohlc", "tick_bracket"],
)
class PrecloseResponse:
    """Day-session continuation/reversal off the move from the day open to a pre-close decision instant.

    Every trade_date resets on its first DAY bar. The official day open/close
    instants come from SessionClock, never guessed from the first observed row.
    The decision instant D = session_close - minutes_before_close is a wall-clock
    instant; because bars are keyed by their own start timestamp and confirm one
    minute later, the bar that confirms exactly at D has ts_jst = D - 1 minute
    ("the decision bar"). Only that exact bar, observed and eligible, is ever
    used to decide; a later bar is never substituted for a missing or ineligible
    decision bar, and once a decision bar is reached (or passed) the trade_date
    resolves permanently with no re-evaluation.

    Day open price Od is defined only from a bar whose ts_jst exactly equals the
    official session_open and which is eligible; if that exact bar is missing or
    not eligible, Od is never defined and the trade_date is skipped. Only bars
    observed within the closed window [session_open, decision_bar_ts] are folded
    into a SessionOHLC (missing bars are never imputed and bar counts are never
    substituted for elapsed minutes); its finalized close is Ct and its
    finalized high/low give W = H - L. If the decision instant does not fall
    strictly after session_open, or the decision bar is missing or ineligible,
    or W is not strictly positive, or Ct equals Od, the trade_date is skipped.

    day_direction = abs(Ct - Od) / W must be at least min_day_direction to form a
    candidate. The candidate direction is sign(Ct - Od) under policy=continuation
    or its negation under policy=reversal. A signal fires only when the candidate
    direction equals the configured direction and no position is already open;
    this check happens at most once per trade_date regardless of outcome.
    stop_ticks and target_ticks are derived from stop_fraction/reward_multiple
    against W and passed to tick_bracket with the decision bar's close Ct as
    reference, so stop/target levels never depend on the next, unknown fill
    price. At most max_entry_signals_per_session signals are emitted per
    trade_date, and the budget is spent at signal time regardless of whether the
    resulting order later fills.
    """

    strategy_id = "preclose_response"
    strategy_version = "1"

    def __init__(
        self,
        direction: str,
        min_day_direction: float,
        minutes_before_close: int,
        policy: str,
        reward_multiple: int | float,
        stop_fraction: float,
        tick_size: int = 5,
        sessions_path: str = "config/sessions.yaml",
        max_entry_signals_per_session: int = 1,
    ) -> None:
        if direction not in {"long", "short"}:
            raise ValueError(f"direction must be 'long' or 'short', got {direction!r}")
        if policy not in {"continuation", "reversal"}:
            raise ValueError(f"policy must be 'continuation' or 'reversal', got {policy!r}")
        if minutes_before_close <= 0:
            raise ValueError("minutes_before_close must be positive")
        if not (0 <= min_day_direction <= 1):
            raise ValueError("min_day_direction must be between 0 and 1")
        if stop_fraction <= 0 or reward_multiple <= 0:
            raise ValueError("stop_fraction and reward_multiple must be positive")
        if tick_size <= 0 or max_entry_signals_per_session <= 0:
            raise ValueError("tick_size and max_entry_signals_per_session must be positive")

        self.direction = direction
        self.direction_sign = 1 if direction == "long" else -1
        self.side = Side.LONG if direction == "long" else Side.SHORT
        self.min_day_direction = min_day_direction
        self.minutes_before_close = minutes_before_close
        self.policy = policy
        self.reward_multiple = reward_multiple
        self.stop_fraction = stop_fraction
        self.tick_size = tick_size
        self.sessions_path = sessions_path
        self.max_entry_signals_per_session = max_entry_signals_per_session

        self.clock = SessionClock(sessions_path)
        self.current_trade_date: date | None = None
        self.day_open_ts = None
        self.decision_bar_ts = None
        self.ohlc: SessionOHLC | None = None
        self.open_price: int | None = None
        # phase: collecting | resolved
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
        day_open_ts = self.clock.session_open(trade_date, Session.DAY)
        day_close_ts = self.clock.session_close(trade_date, Session.DAY)
        decision_ts = day_close_ts - timedelta(minutes=self.minutes_before_close)
        decision_bar_ts = decision_ts - timedelta(minutes=1)
        self.day_open_ts = day_open_ts
        self.decision_bar_ts = decision_bar_ts
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

        assert self.ohlc is not None and self.day_open_ts is not None and self.decision_bar_ts is not None

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
            # The decision bar exists but is not eligible; an earlier bar's
            # close is never substituted as Ct.
            self.phase = "resolved"
            return None

        self.ohlc.update(bar.ts_jst, bar.open, bar.high, bar.low, bar.close, bar.is_eligible)

        if not is_decision_bar:
            return None

        # This is the decision bar's exact confirmation; evaluate once and resolve.
        self.phase = "resolved"
        self.ohlc.finalize()
        if self.open_price is None or not self.ohlc.is_tradable:
            return None

        od = self.open_price
        ct = self.ohlc.close
        hi = self.ohlc.high
        lo = self.ohlc.low
        if ct is None or hi is None or lo is None:
            return None
        width = hi - lo
        if width <= 0 or ct == od:
            return None

        day_direction = abs(ct - od) / width
        if day_direction < self.min_day_direction:
            return None

        raw_sign = 1 if ct > od else -1
        candidate_sign = raw_sign if self.policy == "continuation" else -raw_sign
        if candidate_sign != self.direction_sign:
            return None

        if self.signals_emitted >= self.max_entry_signals_per_session:
            return None
        if ctx.has_position:
            return None

        self.signals_emitted += 1
        stop_ticks = max(1, math.ceil(self.stop_fraction * width / self.tick_size))
        target_ticks = max(1, math.ceil(self.reward_multiple * stop_ticks))
        stop_price, target_price = tick_bracket(
            self.side, ct, stop_ticks, target_ticks, self.tick_size
        )
        action = SignalAction.ENTER_LONG if self.side is Side.LONG else SignalAction.ENTER_SHORT
        return Signal(
            action=action,
            timestamp=bar.ts_jst,
            stop_price=stop_price,
            target_price=target_price,
            reason="preclose_response",
        )


def create_strategy(parameters: dict[str, Any]) -> PrecloseResponse:
    """Create a fresh instance of PrecloseResponse for one parameter set."""
    return PrecloseResponse(**parameters)
