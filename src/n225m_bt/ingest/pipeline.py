"""Phase 2--4 ingest orchestration, always raw -> Bronze -> Silver -> Gold."""

from __future__ import annotations

from pathlib import Path

from n225m_bt.calendar.classifier import CalendarClassifier
from n225m_bt.calendar.inference import infer_calendar_from_trade_dates
from n225m_bt.calendar.model import ExchangeCalendar
from n225m_bt.config import DataConfig, InstrumentConfig, SessionsConfig
from n225m_bt.ingest.labo225 import read_source_records, write_bronze
from n225m_bt.io.manifest import (
    DatasetManifest,
    canonical_hash,
    merge_dataset_manifests,
)
from n225m_bt.io.parquet import write_partitioned
from n225m_bt.normalize.bars import bars_to_frame, normalize_records
from n225m_bt.normalize.gold import make_gold


def ingest_file(
    source: Path,
    instrument_config: InstrumentConfig,
    sessions_config: SessionsConfig,
    data_config: DataConfig,
    calendar: ExchangeCalendar | None = None,
) -> DatasetManifest:
    """Build reproducible layers from one user file without modifying its bytes."""
    records = list(read_source_records(source, data_config.source_format))
    if not records:
        raise ValueError(f"source {source} contains no data rows")
    source_hash = records[0].source_hash
    bronze = data_config.bronze_root / "source=225labo" / f"series={data_config.series_type.value}"
    write_bronze(records, bronze / f"{source_hash}.parquet", data_config.parquet.compression)
    resolved_calendar = calendar
    if (
        resolved_calendar is None
        and data_config.source_format.source_date_semantics == "ose_trade_date"
    ):
        resolved_calendar = infer_calendar_from_trade_dates(
            (record.trade_date for record in records), sessions_config
        )
        resolved_calendar.to_yaml(data_config.silver_root / "inferred_calendar.yaml")
    classifier = CalendarClassifier(sessions_config, resolved_calendar)
    bars, report = normalize_records(
        records,
        classifier,
        data_config.series_type,
        instrument_config.instrument.tick_size,
        data_config.quality.detect_missing_minutes,
        data_config.quality.detect_statistical_outliers,
        data_config.quality.outlier_return_sigma,
        data_config.source_format.source_date_semantics,
    )
    quality_dir = data_config.silver_root / "quality" / source_hash
    report.write(quality_dir)
    if len(bars) != len(records):
        raise ValueError(
            "Silver build aborted: one or more rows had an unresolvable calendar mapping"
        )
    silver = bars_to_frame(bars, records, data_config.series_type)
    write_partitioned(silver, data_config.silver_root, data_config.parquet.compression)
    gold = make_gold(silver, report, data_config.quality.mode == "strict")
    write_partitioned(gold, data_config.gold_root, data_config.parquet.compression)
    manifest = DatasetManifest(
        schema_version=1,
        source_hashes=tuple(sorted({record.source_hash for record in records})),
        source_adapter_version="2",
        normalization_config_hash=canonical_hash(
            {
                "data": data_config.model_dump(mode="json"),
                "sessions": sessions_config.model_dump(mode="json"),
            }
        ),
        earliest_ts=min(bar.ts_jst for bar in bars).isoformat() if bars else None,
        latest_ts=max(bar.ts_jst for bar in bars).isoformat() if bars else None,
        row_count=len(bars),
        quality_summary=report.summary(),
    )
    source_manifest = data_config.silver_root / "manifests" / f"{source_hash}.json"
    manifest.write(source_manifest)
    aggregate = merge_dataset_manifests(
        [DatasetManifest.from_path(path) for path in sorted(source_manifest.parent.glob("*.json"))]
    )
    aggregate.write(data_config.silver_root / "dataset_manifest.json")
    return manifest
