"""Automatic calendar preparation, independent of proprietary market data."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

from n225m_bt.calendar.gold import (
    TimeObservation, build_calendar_from_gold, calendar_from_observations,
    discover_gold_files, read_observations,
)
from n225m_bt.calendar.model import ExchangeCalendar
from n225m_bt.config import JST, SessionsConfig


@pytest.fixture()
def sessions() -> SessionsConfig:
    return SessionsConfig.model_validate({
        "schema_version": 1, "timezone": "Asia/Tokyo", "instrument": "N225M",
        "regimes": [
            {"id": "before", "effective_from": "2021-09-21", "effective_to": "2024-11-04",
             "day": {"session_open": "08:45", "session_close": "15:15"},
             "night": {"session_open": "16:30", "session_close_next_day": "06:00"}},
            {"id": "after", "effective_from": "2024-11-05", "effective_to": None,
             "day": {"session_open": "08:45", "session_close": "15:45"},
             "night": {"session_open": "17:00", "session_close_next_day": "06:00"}},
        ],
    })


def obs(trade: str, stamp: str, session: str = "night") -> TimeObservation:
    ts = datetime.fromisoformat(stamp).replace(tzinfo=JST)
    return TimeObservation(date.fromisoformat(trade), session, ts, ts, "fixture.parquet")


def test_normal_night_and_roundtrip(sessions, tmp_path):
    records = [obs("2024-11-05", "2024-11-05T10:00", "day"),
               obs("2024-11-06", "2024-11-05T17:01"),
               obs("2024-11-06", "2024-11-06T04:00")]
    calendar, report = calendar_from_observations(records, sessions)
    row = calendar.get(date(2024, 11, 6))
    assert row.night_calendar_start_date == date(2024, 11, 5)
    assert row.previous_trade_date == date(2024, 11, 5)
    assert report["observed_evening_mappings"] == 1
    assert report["warnings"] == []
    path = tmp_path / "calendar.yaml"
    calendar.to_yaml(path)
    assert ExchangeCalendar.from_path(path).get(row.trade_date) == row
    payload = yaml.safe_load(path.read_text())
    assert isinstance(payload["trading_days"][0]["trade_date"], str)


def test_weekend_and_first_date_keep_observed_evening(sessions):
    calendar, report = calendar_from_observations([
        obs("2024-11-11", "2024-11-08T17:00"),
        obs("2024-11-11", "2024-11-09T05:00"),
    ], sessions)
    row = calendar.get(date(2024, 11, 11))
    assert row.night_calendar_start_date == date(2024, 11, 8)
    assert row.previous_trade_date is None
    assert report["warnings"] == []


def test_historical_rule_uses_actual_evening_date(sessions):
    calendar, _ = calendar_from_observations([
        obs("2024-11-05", "2024-11-04T16:30"),
    ], sessions)
    row = calendar.get(date(2024, 11, 5))
    assert row.night_calendar_start_date == date(2024, 11, 4)
    assert row.schedule_version == "after"


def test_morning_only_inference_uses_actual_date_not_trade_date(sessions):
    calendar, report = calendar_from_observations([
        obs("2024-11-11", "2024-11-09T05:00"),
    ], sessions)
    assert calendar.get(date(2024, 11, 11)).night_calendar_start_date == date(2024, 11, 8)
    assert report["morning_only_inferred_mappings"] == 1


def test_day_only_has_no_invented_night(sessions):
    calendar, report = calendar_from_observations([
        obs("2024-11-05", "2024-11-05T10:00", "day"),
    ], sessions)
    row = calendar.get(date(2024, 11, 5))
    assert row.night_calendar_start_date is None
    assert "holiday_status=unknown" in row.source_note
    assert report["dates_without_night_bars"] == 1


def test_two_series_deduplicate_dates(sessions):
    item = obs("2024-11-06", "2024-11-05T17:00")
    _, report = calendar_from_observations([item, item], sessions)
    assert report["trade_dates"] == report["observed_evening_mappings"] == 1


def test_conflicting_evenings_never_silently_choose_one(sessions):
    with pytest.raises(ValueError, match="conflicting night start"):
        calendar_from_observations([
            obs("2024-11-11", "2024-11-08T17:00"),
            obs("2024-11-11", "2024-11-07T17:00"),
        ], sessions)


def test_inconsistent_morning_is_reported_not_rewritten(sessions):
    calendar, report = calendar_from_observations([
        obs("2024-11-11", "2024-11-08T17:00"),
        obs("2024-11-11", "2024-11-11T05:00"),
    ], sessions)
    assert calendar.get(date(2024, 11, 11)).night_calendar_start_date == date(2024, 11, 8)
    assert len(report["warnings"]) == 1


@pytest.mark.parametrize("records, message", [
    ([], "no observed trading dates"),
    ([obs("2024-11-06", "2024-11-06T09:00")], "outside configured hours"),
    ([obs("2024-11-06", "2024-11-06T17:00")], "expected an earlier"),
    ([obs("2024-11-06", "2024-11-06T10:00", "unknown")], "unsupported session"),
    ([TimeObservation(date(2024, 11, 6), "day", datetime(2024, 11, 6),
                      datetime(2024, 11, 6))], "timezone-naive"),
])
def test_structural_errors(records, message, sessions):
    with pytest.raises(ValueError, match=message):
        calendar_from_observations(records, sessions)


def test_timezone_conversion(sessions):
    stamp = datetime(2024, 11, 5, 8, tzinfo=timezone.utc)
    calendar, _ = calendar_from_observations([
        TimeObservation(date(2024, 11, 6), "night", stamp, stamp)
    ], sessions)
    assert calendar.get(date(2024, 11, 6)).night_calendar_start_date == date(2024, 11, 5)


def test_partition_discovery_separates_series(tmp_path):
    center = tmp_path / "gold/year=2024/month=11/bars.parquet"
    forward = tmp_path / "gold/forward/year=2024/month=11/bars.parquet"
    for path in (center, forward):
        path.parent.mkdir(parents=True)
        path.write_bytes(b"test only")
    assert discover_gold_files([tmp_path / "gold"]) == [center]
    assert set(discover_gold_files([tmp_path / "gold", tmp_path / "gold/forward"])) == {center, forward}
    assert discover_gold_files([tmp_path / "gold", tmp_path / "gold"]) == [center]


def test_empty_root_is_actionable(tmp_path):
    with pytest.raises(ValueError, match="no year="):
        discover_gold_files([tmp_path])


def test_output_is_outside_gold(tmp_path):
    with pytest.raises(ValueError, match="outside Gold"):
        build_calendar_from_gold([tmp_path], tmp_path / "calendar.yaml", tmp_path / "sessions.yaml")


def test_builder_writes_loadable_calendar_without_modifying_gold(sessions, tmp_path, monkeypatch):
    source = tmp_path / "gold/year=2024/month=11/bars.parquet"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"not read by this unit test")
    original = source.read_bytes()
    config = tmp_path / "sessions.yaml"
    config.write_text(yaml.safe_dump(sessions.model_dump(mode="json")), encoding="utf-8")
    monkeypatch.setattr("n225m_bt.calendar.gold.read_observations", lambda paths: iter([
        obs("2024-11-06", "2024-11-05T17:00")]))
    output = tmp_path / "calendar.yaml"
    result = build_calendar_from_gold([tmp_path / "gold"], output, config)
    first = output.read_bytes()
    build_calendar_from_gold([tmp_path / "gold"], output, config)
    assert output.read_bytes() == first
    assert source.read_bytes() == original
    assert result["file_count"] == 1
    assert ExchangeCalendar.from_path(output).get(date(2024, 11, 6)) is not None
    assert json.loads(output.with_suffix(".summary.json").read_text())["trade_dates"] == 1


def test_bad_input_preserves_existing_output(sessions, tmp_path, monkeypatch):
    source = tmp_path / "gold/year=2024/month=11/bars.parquet"
    source.parent.mkdir(parents=True)
    source.touch()
    config = tmp_path / "sessions.yaml"
    config.write_text(yaml.safe_dump(sessions.model_dump(mode="json")), encoding="utf-8")
    monkeypatch.setattr("n225m_bt.calendar.gold.read_observations", lambda paths: iter([]))
    output = tmp_path / "calendar.yaml"
    output.write_text("keep this old calendar", encoding="utf-8")
    with pytest.raises(ValueError, match="no observed"):
        build_calendar_from_gold([tmp_path / "gold"], output, config)
    assert output.read_text() == "keep this old calendar"


def test_module_help_needs_no_gold_or_agents():
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(root / "src"))
    result = subprocess.run([sys.executable, "-m", "n225m_bt.calendar.gold", "--help"],
                            cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "--gold-root" in result.stdout


def test_real_parquet_reads_only_canonical_time_columns(sessions, tmp_path):
    pl = pytest.importorskip("polars")
    source = tmp_path / "year=2024/month=11/bars.parquet"
    source.parent.mkdir(parents=True)
    stamps = [datetime(2024, 11, 5, 17, tzinfo=JST), datetime(2024, 11, 6, 4, tzinfo=JST)]
    # No OHLC columns: this command must not depend on price data.
    pl.DataFrame({"trade_date": [date(2024, 11, 6)] * 2,
                  "session": ["night"] * 2, "ts_jst": stamps}).write_parquet(source)
    observations = list(read_observations([source]))
    calendar, _ = calendar_from_observations(observations, sessions)
    assert calendar.get(date(2024, 11, 6)).night_calendar_start_date == date(2024, 11, 5)


def test_real_parquet_missing_columns_and_naive_timestamps(tmp_path):
    pl = pytest.importorskip("polars")
    source = tmp_path / "bars.parquet"
    pl.DataFrame({"old_date": ["2024-11-06"]}).write_parquet(source)
    with pytest.raises(ValueError, match="missing canonical Gold columns"):
        list(read_observations([source]))
    pl.DataFrame({"trade_date": [date(2024, 11, 6)], "session": ["night"],
                  "ts_jst": [datetime(2024, 11, 5, 17)]}).write_parquet(source)
    with pytest.raises(ValueError, match="timezone-aware"):
        list(read_observations([source]))
