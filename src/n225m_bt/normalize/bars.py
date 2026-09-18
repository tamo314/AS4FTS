"""Transform Bronze records into canonical Silver bars with JST metadata."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Literal

import polars as pl

from n225m_bt.calendar.classifier import CalendarClassifier
from n225m_bt.domain import Bar, SeriesType
from n225m_bt.ingest.labo225 import SourceRecord
from n225m_bt.quality.checks import validate_bars
from n225m_bt.quality.report import QualityIssue, QualityReport, Severity


def normalize_records(
    records: list[SourceRecord],
    classifier: CalendarClassifier,
    series_type: SeriesType,
    tick_size: int,
    detect_missing_minutes: bool = True,
    detect_statistical_outliers: bool = True,
    outlier_return_sigma: float = 12.0,
    source_date_semantics: str = "ose_trade_date",
) -> tuple[list[Bar], QualityReport]:
    report = QualityReport()
    bars: list[Bar] = []
    bar_records: list[SourceRecord] = []
    for record in records:
        try:
            classified = classifier.reconstruct(
                record.trade_date,
                record.source_time,
                source_date_semantics,
            )
        except ValueError as error:
            report.add(
                QualityIssue(
                    "CALENDAR_UNCERTAIN",
                    Severity.FATAL,
                    str(error),
                    record.source_file,
                    record.source_row_number,
                )
            )
            continue
        bars.append(
            Bar(
                classified.ts_jst,
                classified.trade_date,
                classified.calendar_date,
                classified.session,
                classified.schedule_version,
                record.open,
                record.high,
                record.low,
                record.close,
                record.volume,
                classified.is_session_open,
                classified.is_session_close,
            )
        )
        bar_records.append(record)
    flags = validate_bars(
        bars,
        tick_size,
        report,
        classifier,
        detect_missing_minutes,
        detect_statistical_outliers,
        outlier_return_sigma,
    )
    report.enrich_lineage(
        {
            bar.ts_jst.isoformat(): (
                record.source_file,
                record.source_row_number,
                bar.calendar_date.isoformat(),
                bar.session.value,
            )
            for bar, record in zip(bars, bar_records, strict=True)
        }
    )
    ineligible = {"OHLC_INVARIANT", "NON_POSITIVE_PRICE", "INVALID_VOLUME", "DUPLICATE_TIMESTAMP"}
    normalized = [
        replace(
            bar,
            quality_flags=flags[index],
            is_missing_prev_expected="MISSING_PREV_EXPECTED" in flags[index],
            is_eligible=not any(flag in ineligible for flag in flags[index]),
        )
        for index, bar in enumerate(bars)
    ]
    return normalized, report


def bars_to_frame(
    bars: list[Bar], source_records: list[SourceRecord], series_type: SeriesType
) -> pl.DataFrame:
    if len(bars) != len(source_records):
        raise ValueError("bar/lineage counts must match")
    return pl.DataFrame(
        {
            "ts_jst": [bar.ts_jst for bar in bars],
            "trade_date": [bar.trade_date for bar in bars],
            "calendar_date": [bar.calendar_date for bar in bars],
            "session": [bar.session.value for bar in bars],
            "schedule_version": [bar.schedule_version for bar in bars],
            "instrument": ["N225M"] * len(bars),
            "series_type": [series_type.value] * len(bars),
            "contract_month": [None] * len(bars),
            "open": [bar.open for bar in bars],
            "high": [bar.high for bar in bars],
            "low": [bar.low for bar in bars],
            "close": [bar.close for bar in bars],
            "volume": [bar.volume for bar in bars],
            "is_session_open": [bar.is_session_open for bar in bars],
            "is_session_close": [bar.is_session_close for bar in bars],
            "is_missing_prev_expected": [bar.is_missing_prev_expected for bar in bars],
            "roll_risk": [bar.roll_risk for bar in bars],
            "is_eligible": [bar.is_eligible for bar in bars],
            "quality_flags": [list(bar.quality_flags) for bar in bars],
            "source": ["225labo"] * len(bars),
            "source_file": [record.source_file for record in source_records],
            "source_row_number": [record.source_row_number for record in source_records],
        }
    )


def write_silver(
    frame: pl.DataFrame,
    output: Path,
    compression: Literal["lz4", "uncompressed", "snappy", "gzip", "brotli", "zstd"] = "zstd",
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.sort("ts_jst").write_parquet(output, compression=compression)
