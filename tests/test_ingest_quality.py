from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from n225m_bt.config import JST
from n225m_bt.domain import Bar, SeriesType, Session
from n225m_bt.ingest.labo225 import inspect_source_file, read_source_records
from n225m_bt.ingest.pipeline import ingest_file
from n225m_bt.io.parquet import scan_bars, write_partitioned
from n225m_bt.normalize.bars import normalize_records
from n225m_bt.normalize.gold import make_gold
from n225m_bt.quality.checks import validate_bars
from n225m_bt.quality.report import QualityIssue, QualityReport, Severity


def test_cp932_auto_mapping_and_missing_minute(
    workspace_tmp: Path, classifier: object, project_config: tuple[object, object, object, object]
) -> None:
    path = workspace_tmp / "sample.csv"
    original = "日付,時間,始値,高値,安値,終値,出来高\n2024-11-05,10:00,40000,40005,39995,40000,3\n2024-11-05,10:02,40000,40003,39995,40000,0\n".encode(
        "cp932"
    )
    path.write_bytes(original)
    data = project_config[2]
    inspection = inspect_source_file(path, data.source_format)  # type: ignore[attr-defined]
    assert inspection.encoding == "cp932" and inspection.missing_required == ()
    records = list(read_source_records(path, data.source_format))  # type: ignore[attr-defined]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == hashlib.sha256(original).hexdigest()
    bars, report = normalize_records(records, classifier, SeriesType.CENTER_CONTINUOUS, 5)  # type: ignore[arg-type]
    assert len(bars) == 2
    assert "MISSING_PREV_EXPECTED" in bars[1].quality_flags
    assert "TICK_GRID_VIOLATION" in bars[1].quality_flags
    assert report.has_error is False


def test_missing_required_column_has_actionable_error(
    workspace_tmp: Path, project_config: tuple[object, object, object, object]
) -> None:
    path = workspace_tmp / "bad.csv"
    path.write_text("date,time,open,high,low\n2024-11-05,10:00,1,2,0\n")
    with pytest.raises(ValueError, match="candidate_headers"):
        list(read_source_records(path, project_config[2].source_format))  # type: ignore[attr-defined]


def test_pipeline_writes_bronze_silver_gold_and_manifest(
    workspace_tmp: Path, project_config: tuple[object, object, object, object]
) -> None:
    path = workspace_tmp / "source.csv"
    path.write_text(
        "date,time,open,high,low,close,volume\n2024-11-05,10:00,40000,40005,39995,40000,1\n"
    )
    instrument, sessions, data, _ = project_config
    source_format = data.source_format.model_copy(update={"source_mapping": "auto"})  # type: ignore[attr-defined]
    data = data.model_copy(  # type: ignore[attr-defined]
        update={
            "bronze_root": workspace_tmp / "bronze",
            "silver_root": workspace_tmp / "silver",
            "gold_root": workspace_tmp / "gold",
            "source_format": source_format,
        }
    )
    manifest = ingest_file(path, instrument, sessions, data)  # type: ignore[arg-type]
    assert manifest.row_count == 1 and len(manifest.dataset_id) == 64
    assert (workspace_tmp / "silver" / "dataset_manifest.json").exists()
    assert list((workspace_tmp / "gold").glob("year=*/month=*/*.parquet"))
    filtered = scan_bars(
        workspace_tmp / "gold",
        start_trade_date=date(2024, 11, 5),
        end_trade_date=date(2024, 11, 5),
        session="day",
        eligible_only=True,
    ).collect()
    assert filtered.height == 1


def quality_bar(timestamp: datetime, close: int = 40000) -> Bar:
    return Bar(
        timestamp,
        date(2024, 11, 5),
        timestamp.date(),
        Session.DAY,
        "ose_n225m_from_20241105",
        40000,
        max(40005, close),
        39995,
        close,
    )


def test_expected_grid_reports_missing_minutes_without_synthetic_bars(classifier: object) -> None:
    only_open = quality_bar(datetime(2024, 11, 5, 8, 45, tzinfo=JST))
    report = QualityReport()
    flags = validate_bars([only_open], 5, report, classifier)  # type: ignore[arg-type]
    assert len(flags) == 1
    assert any(issue.code == "MISSING_EXPECTED_MINUTES" for issue in report.issues)


def test_conflicting_duplicate_ohlc_and_strict_gold_gate() -> None:
    timestamp = datetime(2024, 11, 5, 10, 0, tzinfo=JST)
    bars = [quality_bar(timestamp), quality_bar(timestamp, 40005)]
    report = QualityReport()
    flags = validate_bars(bars, 5, report, detect_missing_minutes=False)
    assert "DUPLICATE_TIMESTAMP" in flags[0]
    assert report.has_error
    frame = pl.DataFrame(
        {
            "ts_jst": [timestamp],
            "trade_date": [date(2024, 11, 5)],
            "session": ["day"],
            "close": [40000],
        }
    )
    with pytest.raises(ValueError, match="blocked"):
        make_gold(frame, report, strict=True)


def test_statistical_price_jump_is_flagged_but_not_error() -> None:
    start = datetime(2024, 11, 5, 10, 0, tzinfo=JST)
    bars = [quality_bar(start + timedelta(minutes=index), 40000) for index in range(4)]
    bars.append(quality_bar(start + timedelta(minutes=4), 40100))
    report = QualityReport()
    flags = validate_bars(
        bars,
        5,
        report,
        detect_missing_minutes=False,
        outlier_return_sigma=0.5,
    )
    assert "STATISTICAL_PRICE_JUMP" in flags[4]
    assert report.has_error is False


def test_quality_summary_groups_by_date_and_session() -> None:
    report = QualityReport()
    report.add(
        QualityIssue(
            "TEST",
            Severity.WARN,
            "test issue",
            calendar_date="2024-11-05",
            session="day",
        )
    )
    summary = report.summary()
    assert summary["by_year"] == {"2024": 1}
    assert summary["by_month"] == {"2024-11": 1}
    assert summary["by_session"] == {"day": 1}


def test_quality_report_parquet_keeps_late_optional_timestamp(workspace_tmp: Path) -> None:
    report = QualityReport()
    for _ in range(101):
        report.add(QualityIssue("NO_TIMESTAMP", Severity.WARN, "no timestamp"))
    report.add(
        QualityIssue(
            "WITH_TIMESTAMP",
            Severity.WARN,
            "timestamp present",
            ts_jst="2020-01-24T09:17:00+09:00",
        )
    )
    report.write(workspace_tmp / "quality")
    issues = pl.read_parquet(workspace_tmp / "quality" / "quality_issues.parquet")
    assert issues.filter(pl.col("code") == "WITH_TIMESTAMP")["ts_jst"].item() == (
        "2020-01-24T09:17:00+09:00"
    )


def test_partitioned_writes_merge_adjacent_sources_idempotently(workspace_tmp: Path) -> None:
    root = workspace_tmp / "partitioned"
    first = pl.DataFrame(
        {
            "ts_jst": [datetime(2024, 1, 31, 23, 59, tzinfo=JST)],
            "source_file": ["first.xlsx"],
            "source_row_number": [2],
        }
    )
    second = pl.DataFrame(
        {
            "ts_jst": [datetime(2024, 1, 1, 0, 0, tzinfo=JST)],
            "source_file": ["second.xlsx"],
            "source_row_number": [2],
        }
    )
    write_partitioned(first, root)
    write_partitioned(second, root)
    write_partitioned(second, root)
    result = pl.read_parquet(root / "year=2024" / "month=01" / "bars.parquet")
    assert result.height == 2
