"""Gold data preparation contains eligibility and generic time-derived fields only."""

from __future__ import annotations

import polars as pl

from n225m_bt.quality.report import QualityReport


def make_gold(silver: pl.DataFrame, report: QualityReport, strict: bool) -> pl.DataFrame:
    if report.has_fatal or (strict and report.has_error):
        raise ValueError("Gold dataset generation blocked by quality report")
    return silver.sort("ts_jst").with_columns(
        pl.col("ts_jst").dt.hour().alias("hour"),
        pl.col("ts_jst").dt.weekday().alias("weekday"),
        pl.col("ts_jst").cum_count().over(["trade_date", "session"]).alias("session_minute_index"),
        pl.col("close").pct_change().alias("close_return"),
    )
