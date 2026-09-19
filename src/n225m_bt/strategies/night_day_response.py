"""Night-session directional response adapter over session clock, session OHLC, and tick brackets."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

from n225m_bt.calendar.classifier import CalendarClassifier
from n225m_bt.components import component
from n225m_bt.components.primitives import tick_bracket
from n225m_bt.components.session_clock import SessionClock
from n225m_bt.components.session_ohlc import SessionOHLC
from n225m_bt.domain import Bar, Session, Side, Signal, SignalAction
from n225m_bt.strategies.base import StrategyContext


@component(
    id="night_day_response",
    kind="strategy",
    summary="Trades the day-session open response to a directionally decisive prior night session",
    tags=["night", "session", "continuation", "reversal", "intraday"],
    uses=["session_clock", "session_ohlc", "tick_bracket"],
)
class NightDayResponse:
    """Day-session continuation/reversal of a directionally decisive prior night session.

    Every bar is keyed by its own trade_date, which NIGHT and DAY bars for the
    same trading day share. While NIGHT bars for the current trade_date arrive,
    each is folded into a SessionOHLC bounded by that trade_date's official
    night session_open/session_close from SessionClock; no boundary is guessed
    from the first observed row. The first DAY bar for the trade_date finalizes
    that night window. If no eligible night bar was observed, the window is not
    tradable, On equals Cn, or the resulting night direction fraction
    abs(Cn-On)/(Hn-Ln) is strictly below min_night_direction, the trade_date is
    skipped with no further action.

    Otherwise the strategy waits for the DAY bar whose timestamp exactly equals
    the official day session_open; if that exact eligible bar is absent the
    trade_date is skipped (no earlier or later bar is substituted). That bar's
    open is the day open price. The strategy then waits for the DAY bar whose
    timestamp exactly equals session_open + confirmation_minutes - 1 minute (so
    its confirmation instant ts_jst+1 minute lands exactly on the deadline); if
    a later bar arrives without ever exactly matching, the trade_date is
    skipped without retroactively adopting that later bar. On the exact match,
    the candidate direction is the night direction under policy=continuation or
    its negation under policy=reversal. A signal fires only if the sign of
    (confirmation close - day open) equals the candidate direction and the
    candidate direction equals the configured direction; this check happens at
    most once per trade_date regardless of outcome. stop_ticks and target_ticks
    are derived from stop_fraction/reward_multiple against the night width W
    and passed to tick_bracket with the confirmation close as reference. At
    most max_entry_signals_per_session signals are emitted per trade_date.
    """

    strategy_id = "night_day_response"
    strategy_version = "2"

    def __init__(
        self,
        confirmation_minutes: int,
        direction: str,
        min_night_direction: float,
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
        if confirmation_minutes <= 0:
            raise ValueError("confirmation_minutes must be positive")
        if not (0 <= min_night_direction <= 1):
            raise ValueError("min_night_direction must be between 0 and 1")
        if stop_fraction <= 0 or reward_multiple <= 0:
            raise ValueError("stop_fraction and reward_multiple must be positive")
        if tick_size <= 0 or max_entry_signals_per_session <= 0:
            raise ValueError("tick_size and max_entry_signals_per_session must be positive")

        self.confirmation_minutes = confirmation_minutes
        self.direction = direction
        self.direction_sign = 1 if direction == "long" else -1
        self.side = Side.LONG if direction == "long" else Side.SHORT
        self.min_night_direction = min_night_direction
        self.policy = policy
        self.reward_multiple = reward_multiple
        self.stop_fraction = stop_fraction
        self.tick_size = tick_size
        self.sessions_path = sessions_path
        self.max_entry_signals_per_session = max_entry_signals_per_session

        self.clock = SessionClock(sessions_path)
        self.current_trade_date: date | None = None
        self.night_ohlc: SessionOHLC | None = None
        self.night_direction: int | None = None
        self.night_width: int | None = None
        self.day_open_ts: datetime | None = None
        self.confirmation_target_ts: datetime | None = None
        self.open_price: int | None = None
        # phase: collecting_night | awaiting_day_open | awaiting_confirmation | resolved
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
        self.night_direction = None
        self.night_width = None
        self.open_price = None
        self.confirmation_target_ts = None
        self.day_open_ts = self.clock.session_open(trade_date, Session.DAY)
        # No observed night is a valid no-trade condition. Initialize the night
        # window only on an observed NIGHT bar. Missing calendar mappings for
        # such bars are execution errors, never silently successful zero trades.
        self.night_ohlc = None
        self.phase = "collecting_night"

    def _finalize_night(self) -> None:
        if self.night_ohlc is None:
            self.phase = "resolved"
            return
        self.night_ohlc.finalize()
        if not self.night_ohlc.is_tradable:
            self.phase = "resolved"
            return
        on = self.night_ohlc.open
        cn = self.night_ohlc.close
        width = self.night_ohlc.width
        if on is None or cn is None or width is None or width <= 0 or cn == on:
            self.phase = "resolved"
            return
        fraction = abs(cn - on) / width
        if fraction < self.min_night_direction:
            self.phase = "resolved"
            return
        self.night_direction = 1 if cn > on else -1
        self.night_width = width
        self.phase = "awaiting_day_open"

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> Signal | None:
        if bar.trade_date != self.current_trade_date:
            self._reset_for_trade_date(bar.trade_date)

        if self.phase == "resolved":
            return None

        if bar.session is Session.NIGHT:
            if self.night_ohlc is None:
                # Propagate calendar errors so the runner records a failed case.
                self.night_ohlc = SessionOHLC(
                    self.clock.session_open(bar.trade_date, Session.NIGHT),
                    self.clock.session_close(bar.trade_date, Session.NIGHT),
                )
            self.night_ohlc.update(bar.ts_jst, bar.open, bar.high, bar.low, bar.close, bar.is_eligible)
            return None

        # bar.session is Session.DAY from here.
        if self.phase == "collecting_night":
            self._finalize_night()
            if self.phase == "resolved":
                return None

        if self.phase == "awaiting_day_open":
            if self.day_open_ts is None or bar.ts_jst != self.day_open_ts:
                self.phase = "resolved"
                return None
            self.open_price = bar.open
            self.confirmation_target_ts = (
                self.day_open_ts + timedelta(minutes=self.confirmation_minutes) - timedelta(minutes=1)
            )
            self.phase = "awaiting_confirmation"
            return None

        if self.phase == "awaiting_confirmation":
            assert self.confirmation_target_ts is not None
            if bar.ts_jst < self.confirmation_target_ts:
                return None
            self.phase = "resolved"
            if bar.ts_jst != self.confirmation_target_ts:
                return None
            if self.open_price is None or self.night_direction is None or self.night_width is None:
                return None
            if self.signals_emitted >= self.max_entry_signals_per_session:
                return None
            if ctx.has_position:
                return None

            confirmation_close = bar.close
            day_change = confirmation_close - self.open_price
            if day_change == 0:
                return None
            day_direction = 1 if day_change > 0 else -1
            candidate_direction = (
                self.night_direction if self.policy == "continuation" else -self.night_direction
            )
            if day_direction != candidate_direction or candidate_direction != self.direction_sign:
                return None

            self.signals_emitted += 1
            stop_ticks = max(1, math.ceil(self.stop_fraction * self.night_width / self.tick_size))
            target_ticks = max(1, math.ceil(self.reward_multiple * stop_ticks))
            stop_price, target_price = tick_bracket(
                self.side, confirmation_close, stop_ticks, target_ticks, self.tick_size
            )
            action = SignalAction.ENTER_LONG if self.side is Side.LONG else SignalAction.ENTER_SHORT
            return Signal(
                action=action,
                timestamp=bar.ts_jst,
                stop_price=stop_price,
                target_price=target_price,
                reason="night_day_response",
            )

        return None


def create_strategy(parameters: dict[str, Any]) -> NightDayResponse:
    """Create a fresh instance of NightDayResponse for one parameter set."""
    return NightDayResponse(**parameters)
