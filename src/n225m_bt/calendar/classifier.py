"""Classify JST timestamps without guessing exchange holidays."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from n225m_bt.calendar.model import ExchangeCalendar
from n225m_bt.calendar.session_rules import regime_for_trade_date
from n225m_bt.config import JST, SessionRegime, SessionsConfig
from n225m_bt.domain import Session


@dataclass(frozen=True, slots=True)
class ClassifiedTime:
    ts_jst: datetime
    calendar_date: date
    trade_date: date
    session: Session
    schedule_version: str
    is_session_open: bool
    is_session_close: bool


class CalendarClassifier:
    def __init__(
        self, sessions: SessionsConfig, exchange_calendar: ExchangeCalendar | None = None
    ) -> None:
        self.sessions = sessions
        self.exchange_calendar = exchange_calendar or ExchangeCalendar()

    def classify_timestamp(
        self, ts_jst: datetime, trade_date: date | None = None
    ) -> ClassifiedTime:
        if ts_jst.tzinfo is None or ts_jst.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware Asia/Tokyo")
        local = ts_jst.astimezone(JST)
        candidates = (
            [trade_date] if trade_date else [local.date(), local.date() + timedelta(days=1)]
        )
        for candidate in candidates:
            assert candidate is not None
            try:
                classified = self._classify_candidate(local, candidate)
            except ValueError:
                continue
            if classified is not None:
                return classified
        raise ValueError(
            f"timestamp {local.isoformat()} is outside configured sessions or trade-date mapping"
        )

    def reconstruct(
        self,
        source_date: date,
        source_time: time,
        source_date_semantics: str = "ose_trade_date",
    ) -> ClassifiedTime:
        """Reconstruct a source time using explicit calendar mapping for night bars."""
        if source_date_semantics == "actual_calendar_date":
            return self._reconstruct_actual_calendar_date(source_date, source_time)
        if source_date_semantics != "ose_trade_date":
            raise ValueError(f"unknown source_date_semantics={source_date_semantics!r}")
        day = self.exchange_calendar.get(source_date)
        night_start = day.night_calendar_start_date if day is not None else None
        night_regime = (
            regime_for_trade_date(self.sessions, night_start)
            if night_start is not None
            else regime_for_trade_date(self.sessions, source_date)
        )
        if night_regime.night.session_open <= source_time:
            if night_start is None:
                raise ValueError(
                    "night timestamp requires explicit exchange calendar mapping for "
                    f"trade_date={source_date.isoformat()}"
                )
            local = datetime.combine(night_start, source_time, JST)
        else:
            local = datetime.combine(source_date, source_time, JST)
        return self.classify_timestamp(local, source_date)

    def _reconstruct_actual_calendar_date(
        self, source_date: date, source_time: time
    ) -> ClassifiedTime:
        local = datetime.combine(source_date, source_time, JST)
        source_regime = regime_for_trade_date(self.sessions, source_date)
        if source_time >= source_regime.night.session_open:
            trade_date = self.exchange_calendar.trade_date_for_night_start(source_date)
            if trade_date is None:
                raise ValueError(
                    "evening source date has no inferred/explicit next trade-date mapping for "
                    f"calendar_date={source_date.isoformat()}"
                )
            return self.classify_timestamp(local, trade_date)
        return self.classify_timestamp(local, source_date)

    def session_close(self, trade_date: date, session: Session) -> datetime:
        regime = self._regime_for_session(trade_date, session)
        fields = regime.day if session is Session.DAY else regime.night
        if fields.session_close is not None:
            return datetime.combine(trade_date, fields.session_close, JST)
        assert fields.session_close_next_day is not None
        # trade_date labels the morning on which the preceding evening session ends.
        return datetime.combine(trade_date, fields.session_close_next_day, JST)

    def session_open(self, trade_date: date, session: Session) -> datetime:
        """Return the actual JST opening instant for one exchange session."""
        regime = self._regime_for_session(trade_date, session)
        fields = regime.day if session is Session.DAY else regime.night
        if session is Session.DAY:
            return datetime.combine(trade_date, fields.session_open, JST)
        day = self.exchange_calendar.get(trade_date)
        if day is None or day.night_calendar_start_date is None:
            raise ValueError(
                "night expected-minute grid requires an explicit exchange calendar mapping for "
                f"trade_date={trade_date.isoformat()}"
            )
        return datetime.combine(day.night_calendar_start_date, fields.session_open, JST)

    def _regime_for_session(self, trade_date: date, session: Session) -> SessionRegime:
        if session is Session.DAY:
            return regime_for_trade_date(self.sessions, trade_date)
        day = self.exchange_calendar.get(trade_date)
        if day is None or day.night_calendar_start_date is None:
            raise ValueError(
                "night session requires explicit exchange calendar mapping for "
                f"trade_date={trade_date.isoformat()}"
            )
        return regime_for_trade_date(self.sessions, day.night_calendar_start_date)

    def _classify_candidate(self, local: datetime, trade_date: date) -> ClassifiedTime | None:
        day_regime = regime_for_trade_date(self.sessions, trade_date)
        day_open = datetime.combine(trade_date, day_regime.day.session_open, JST)
        day_close = self.session_close(trade_date, Session.DAY)
        night_open_date = self.exchange_calendar.get(trade_date)
        evening_date = night_open_date.night_calendar_start_date if night_open_date else None
        if evening_date is not None:
            night_regime = regime_for_trade_date(self.sessions, evening_date)
            night_open = datetime.combine(evening_date, night_regime.night.session_open, JST)
            night_close = self.session_close(trade_date, Session.NIGHT)
            if night_open <= local <= night_close:
                return ClassifiedTime(
                    local,
                    local.date(),
                    trade_date,
                    Session.NIGHT,
                    night_regime.id,
                    local == night_open,
                    local == night_close,
                )
        if day_open <= local <= day_close:
            return ClassifiedTime(
                local,
                local.date(),
                trade_date,
                Session.DAY,
                day_regime.id,
                local == day_open,
                local == day_close,
            )
        return None
