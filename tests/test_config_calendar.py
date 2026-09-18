from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path

import pytest

from n225m_bt.calendar.classifier import CalendarClassifier
from n225m_bt.calendar.model import ExchangeCalendar, TradingDay
from n225m_bt.calendar.session_rules import regime_for_trade_date
from n225m_bt.config import (
    JST,
    InstrumentConfig,
    load_project_config,
    load_research_config,
    load_yaml_model,
)
from n225m_bt.domain import Session


def test_provided_yaml_configs_validate() -> None:
    instrument, sessions, data, backtest = load_project_config(Path("config"))
    assert instrument.instrument.symbol == data.instrument == backtest.instrument
    assert len(sessions.regimes) == 3
    assert load_research_config(Path("config")).walk_forward.train_months == 12


def test_unknown_instrument_key_is_rejected(workspace_tmp: Path) -> None:
    path = workspace_tmp / "instrument.yaml"
    path.write_text("schema_version: 1\ninstrument: {symbol: N225M, unknown: nope}\n")
    with pytest.raises(ValueError, match="unknown"):
        load_yaml_model(path, InstrumentConfig)


def test_regime_boundaries_and_classification(classifier: CalendarClassifier) -> None:
    sessions = classifier.sessions
    assert regime_for_trade_date(sessions, date(2021, 9, 20)).id.endswith("20210920")
    assert regime_for_trade_date(sessions, date(2021, 9, 21)).id.endswith("20241104")
    assert regime_for_trade_date(sessions, date(2024, 11, 4)).id.endswith("20241104")
    assert regime_for_trade_date(sessions, date(2024, 11, 5)).id.endswith("20241105")
    day = classifier.classify_timestamp(datetime(2024, 11, 5, 8, 45, tzinfo=JST), date(2024, 11, 5))
    assert day.session is Session.DAY and day.is_session_open


def test_night_calendar_date_is_not_unconditional_previous_day(
    classifier: CalendarClassifier,
) -> None:
    classified = classifier.reconstruct(date(2024, 11, 5), time(17, 30))
    assert classified.trade_date == date(2024, 11, 5)
    assert classified.calendar_date == date(2024, 11, 4)
    assert classified.session is Session.NIGHT


def test_night_session_uses_its_actual_start_date_regime(
    project_config: tuple[object, object, object, object],
) -> None:
    calendar = ExchangeCalendar(
        [
            TradingDay(
                date(2024, 11, 5),
                date(2024, 11, 1),
                None,
                date(2024, 11, 4),
                False,
                "ose_n225m_from_20241105",
            )
        ]
    )
    classifier = CalendarClassifier(project_config[1], calendar)  # type: ignore[arg-type]
    night = classifier.reconstruct(date(2024, 11, 5), time(16, 30))
    day = classifier.reconstruct(date(2024, 11, 5), time(8, 45))
    assert night.calendar_date == date(2024, 11, 4)
    assert night.schedule_version.endswith("20241104")
    assert day.schedule_version.endswith("20241105")


def test_unmapped_night_time_fails_explicitly(
    project_config: tuple[object, object, object, object],
) -> None:
    classifier = CalendarClassifier(project_config[1])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="explicit exchange calendar"):
        classifier.reconstruct(date(2024, 11, 5), time(17, 30))
