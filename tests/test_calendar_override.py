from __future__ import annotations

from datetime import date
from pathlib import Path

from n225m_bt.calendar.model import ExchangeCalendar


def test_yaml_calendar_override_loads_explicit_night_mapping(workspace_tmp: Path) -> None:
    path = workspace_tmp / "calendar.yaml"
    path.write_text(
        "trading_days:\n"
        "  - trade_date: '2024-11-05'\n"
        "    previous_trade_date: '2024-11-04'\n"
        "    next_trade_date: ''\n"
        "    night_calendar_start_date: '2024-11-04'\n"
        "    is_holiday_trading_day: false\n"
        "    schedule_version: ose_n225m_from_20241105\n",
        encoding="utf-8",
    )
    calendar = ExchangeCalendar.from_path(path)
    assert calendar.get(date(2024, 11, 5)).night_calendar_start_date == date(2024, 11, 4)  # type: ignore[union-attr]
