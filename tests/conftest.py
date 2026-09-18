from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from n225m_bt.calendar.classifier import CalendarClassifier
from n225m_bt.calendar.model import ExchangeCalendar, TradingDay
from n225m_bt.config import JST, load_project_config
from n225m_bt.domain import Bar, Session


@pytest.fixture()
def project_config() -> tuple[object, object, object, object]:
    return load_project_config(Path("config"))


@pytest.fixture()
def classifier(project_config: tuple[object, object, object, object]) -> CalendarClassifier:
    sessions = project_config[1]
    calendar = ExchangeCalendar(
        [
            TradingDay(date(2021, 9, 21), date(2021, 9, 20), None, date(2021, 9, 20), False, ""),
            TradingDay(date(2024, 11, 5), date(2024, 11, 4), None, date(2024, 11, 4), False, ""),
        ]
    )
    return CalendarClassifier(sessions, calendar)  # type: ignore[arg-type]


@pytest.fixture()
def workspace_tmp(request: pytest.FixtureRequest) -> Path:
    """Workspace-local test files avoid a restricted Windows system temp directory."""
    path = Path(".test-artifacts") / request.node.name
    path.mkdir(parents=True, exist_ok=True)
    return path


def make_bar(
    ts: datetime,
    trade_date: date,
    *,
    open_: int = 40000,
    high: int = 40005,
    low: int = 39995,
    close: int = 40000,
) -> Bar:
    return Bar(
        ts.replace(tzinfo=JST), trade_date, ts.date(), Session.DAY, "test", open_, high, low, close
    )
