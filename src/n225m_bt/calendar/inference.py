"""Build explicit exchange-calendar mappings from observed 225Labo trade dates."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from n225m_bt.calendar.model import ExchangeCalendar, TradingDay
from n225m_bt.calendar.session_rules import regime_for_trade_date
from n225m_bt.config import SessionsConfig


def infer_calendar_from_trade_dates(
    trade_dates: Iterable[date], sessions: SessionsConfig
) -> ExchangeCalendar:
    """Create calendar rows from dates present in the source, without holiday guesses.

    A 225Labo record's date labels an OSE trade date. Its night session begins
    on the previous *observed trading date*, which may not be the preceding
    civil day around weekends and exchange holidays. The caller must supply the
    complete observed date set that covers its intended ingestion range.
    """
    dates = sorted(set(trade_dates))
    if not dates:
        raise ValueError("cannot infer exchange calendar: no observed trade dates")
    entries = [
        TradingDay(
            trade_date=trade_date,
            previous_trade_date=dates[index - 1] if index else None,
            next_trade_date=dates[index + 1] if index + 1 < len(dates) else None,
            night_calendar_start_date=dates[index - 1] if index else None,
            is_holiday_trading_day=False,
            schedule_version=regime_for_trade_date(sessions, trade_date).id,
            source_note="inferred_from_observed_225labo_trade_dates",
        )
        for index, trade_date in enumerate(dates)
    ]
    return ExchangeCalendar(entries)
