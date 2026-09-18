"""Calendar override representation; intentionally independent of bank holidays."""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml


@dataclass(frozen=True, slots=True)
class TradingDay:
    trade_date: date
    previous_trade_date: date | None
    next_trade_date: date | None
    night_calendar_start_date: date | None
    is_holiday_trading_day: bool
    schedule_version: str
    source_note: str | None = None


class ExchangeCalendar:
    """Explicit OSE calendar mappings, supplied by data onboarding when needed."""

    def __init__(self, days: list[TradingDay] | None = None) -> None:
        self._days = {item.trade_date: item for item in days or []}

    def get(self, trade_date: date) -> TradingDay | None:
        return self._days.get(trade_date)

    def trade_date_for_night_start(self, calendar_date: date) -> date | None:
        for day in self._days.values():
            if day.night_calendar_start_date == calendar_date:
                return day.trade_date
        return None

    def to_yaml(self, path: Path) -> None:
        rows = [
            {
                "trade_date": item.trade_date.isoformat(),
                "previous_trade_date": item.previous_trade_date.isoformat()
                if item.previous_trade_date
                else "",
                "next_trade_date": item.next_trade_date.isoformat() if item.next_trade_date else "",
                "night_calendar_start_date": item.night_calendar_start_date.isoformat()
                if item.night_calendar_start_date
                else "",
                "is_holiday_trading_day": item.is_holiday_trading_day,
                "schedule_version": item.schedule_version,
                "source_note": item.source_note or "",
            }
            for item in sorted(self._days.values(), key=lambda entry: entry.trade_date)
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump({"trading_days": rows}, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    @classmethod
    def from_csv(cls, path: Path) -> ExchangeCalendar:
        """Load the documented explicit calendar-override table without holiday guessing."""
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        return cls._from_rows(path, rows)

    @classmethod
    def from_path(cls, path: Path) -> ExchangeCalendar:
        """Load an explicit CSV or YAML exchange-calendar override."""
        if path.suffix.casefold() == ".csv":
            return cls.from_csv(path)
        if path.suffix.casefold() not in {".yaml", ".yml"}:
            raise ValueError(f"calendar override {path} must be CSV, YAML, or YML")
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        rows = payload.get("trading_days") if isinstance(payload, dict) else payload
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError(f"calendar override {path} must be a list or a trading_days list")
        return cls._from_rows(path, rows)

    @classmethod
    def _from_rows(cls, path: Path, rows: Sequence[Mapping[str, object]]) -> ExchangeCalendar:
        required = {
            "trade_date",
            "previous_trade_date",
            "next_trade_date",
            "night_calendar_start_date",
            "is_holiday_trading_day",
            "schedule_version",
        }
        if not rows or not required.issubset(rows[0]):
            raise ValueError(
                f"calendar override {path} is missing required columns {sorted(required)}"
            )

        def optional_date(value: object | None) -> date | None:
            return date.fromisoformat(str(value)) if value else None

        def required_text(row: Mapping[str, object], key: str) -> str:
            value = row[key]
            if not isinstance(value, str):
                raise ValueError(f"calendar override {path}: {key} must be a string")
            return value

        def holiday_flag(value: object) -> bool:
            return value is True or str(value).casefold() in {"true", "1", "yes"}

        return cls(
            [
                TradingDay(
                    trade_date=date.fromisoformat(required_text(row, "trade_date")),
                    previous_trade_date=optional_date(row["previous_trade_date"]),
                    next_trade_date=optional_date(row["next_trade_date"]),
                    night_calendar_start_date=optional_date(row["night_calendar_start_date"]),
                    is_holiday_trading_day=holiday_flag(row["is_holiday_trading_day"]),
                    schedule_version=required_text(row, "schedule_version"),
                    source_note=str(row["source_note"]) if row.get("source_note") else None,
                )
                for row in rows
            ]
        )
