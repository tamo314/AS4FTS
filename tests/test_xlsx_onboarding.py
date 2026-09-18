from __future__ import annotations

from datetime import date
from pathlib import Path

from typer.testing import CliRunner

from n225m_bt.calendar.inference import infer_calendar_from_trade_dates
from n225m_bt.cli import app
from n225m_bt.config import load_project_config
from n225m_bt.domain import SeriesType
from n225m_bt.ingest.labo225 import (
    inspect_source_file,
    read_source_records,
    read_source_trade_dates,
)


def write_workbook(path: Path) -> None:
    import openpyxl

    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "1min"
    worksheet.append(["日付", "時間", "始値", "高値", "安値", "終値", "出来高"])
    worksheet.append([date(2024, 11, 5), "10:00", 40000, 40005, 39995, 40000, 1])
    workbook.create_sheet("5min")
    workbook.save(path)


def test_xlsx_adapter_preserves_headers_and_streams_records(workspace_tmp: Path) -> None:
    path = workspace_tmp / "sample.xlsx"
    write_workbook(path)
    data = load_project_config(Path("config"))[2]
    inspection = inspect_source_file(path, data.source_format)
    assert inspection.headers[0] == "日付"
    assert list(read_source_trade_dates(path, data.source_format)) == [date(2024, 11, 5)]
    records = list(read_source_records(path, data.source_format))
    assert len(records) == 1
    assert records[0].close == 40000


def test_inferred_calendar_uses_previous_observed_trade_date() -> None:
    sessions = load_project_config(Path("config"))[1]
    calendar = infer_calendar_from_trade_dates([date(2024, 1, 5), date(2024, 1, 9)], sessions)
    first = calendar.get(date(2024, 1, 5))
    second = calendar.get(date(2024, 1, 9))
    assert first is not None and first.night_calendar_start_date is None
    assert second is not None
    assert second.previous_trade_date == date(2024, 1, 5)
    assert second.night_calendar_start_date == date(2024, 1, 5)


def test_build_calendar_cli_scans_workbooks(workspace_tmp: Path) -> None:
    root = workspace_tmp / "raw"
    root.mkdir(exist_ok=True)
    write_workbook(root / "sample.xlsx")
    output = workspace_tmp / "local_calendar.yaml"
    result = CliRunner().invoke(
        app,
        [
            "data",
            "build-calendar",
            "--source-root",
            str(root),
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert output.exists()


def test_ingest_dataset_namespace_keeps_continuous_series_separate(workspace_tmp: Path) -> None:
    path = workspace_tmp / "sample.xlsx"
    write_workbook(path)
    output = workspace_tmp / "calendar.yaml"
    calendar_result = CliRunner().invoke(
        app,
        [
            "data",
            "build-calendar",
            "--source-root",
            str(workspace_tmp),
            "--output",
            str(output),
        ],
    )
    assert calendar_result.exit_code == 0, calendar_result.stdout
    config_dir = workspace_tmp / "config"
    config_dir.mkdir(exist_ok=True)
    for name in ["instrument.yaml", "sessions.yaml", "backtest.yaml", "research.yaml"]:
        (config_dir / name).write_text(
            (Path("config") / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    data = load_project_config(Path("config"))[2].model_dump(mode="json")
    data.update(
        {
            "bronze_root": str(workspace_tmp / "bronze"),
            "silver_root": str(workspace_tmp / "silver"),
            "gold_root": str(workspace_tmp / "gold"),
        }
    )
    import yaml

    (config_dir / "data.yaml").write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    result = CliRunner().invoke(
        app,
        [
            "data",
            "ingest",
            str(path),
            "--config-dir",
            str(config_dir),
            "--calendar-override",
            str(output),
            "--dataset",
            "forward",
            "--series-type",
            SeriesType.NEXT_CONTINUOUS.value,
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert list((workspace_tmp / "gold" / "forward").rglob("*.parquet"))
