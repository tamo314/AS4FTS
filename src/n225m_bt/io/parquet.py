"""Parquet helpers: scanning stays separate from raw-source ingestion."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import polars as pl

Compression = Literal["lz4", "uncompressed", "snappy", "gzip", "brotli", "zstd"]


def write_partitioned(
    frame: pl.DataFrame, root: Path, compression: Compression = "zstd"
) -> list[Path]:
    """Write deterministic year/month partitions from an already canonical frame."""
    output: list[Path] = []
    enriched = frame.with_columns(
        pl.col("ts_jst").dt.year().alias("year"), pl.col("ts_jst").dt.month().alias("month")
    )
    for keys, partition in enriched.partition_by(
        ["year", "month"], as_dict=True, maintain_order=True
    ).items():
        year, month = keys if isinstance(keys, tuple) else (keys, 1)
        path = root / f"year={year}" / f"month={month:02d}" / "bars.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        partition = partition.drop(["year", "month"])
        if path.exists():
            existing = pl.read_parquet(path)
            if {"source_file", "source_row_number"}.issubset(partition.columns):
                partition = pl.concat([existing, partition]).unique(
                    subset=["source_file", "source_row_number"], keep="last"
                )
        partition.sort("ts_jst").write_parquet(path, compression=compression)
        output.append(path)
    return output


def scan_bars(
    root: Path,
    start_trade_date: date | None = None,
    end_trade_date: date | None = None,
    session: Literal["day", "night"] | None = None,
    eligible_only: bool = False,
) -> pl.LazyFrame:
    """Lazily filter canonical Parquet before materialization."""
    frame = pl.scan_parquet(str(root / "**" / "*.parquet"))
    if start_trade_date is not None:
        frame = frame.filter(pl.col("trade_date") >= pl.lit(start_trade_date))
    if end_trade_date is not None:
        frame = frame.filter(pl.col("trade_date") <= pl.lit(end_trade_date))
    if session is not None:
        frame = frame.filter(pl.col("session") == session)
    if eligible_only:
        frame = frame.filter(pl.col("is_eligible"))
    return frame
