"""Small reproducible performance sanity checks for canonical Parquet scans."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from n225m_bt.io.parquet import scan_bars


@dataclass(frozen=True, slots=True)
class ScanBenchmark:
    row_count: int
    elapsed_seconds: float

    @property
    def rows_per_second(self) -> float:
        return self.row_count / self.elapsed_seconds if self.elapsed_seconds else float("inf")


def benchmark_parquet_scan(root: Path) -> ScanBenchmark:
    """Measure a lazy Parquet row count; it deliberately never opens source CSV files."""
    started = perf_counter()
    row_count = scan_bars(root).select("ts_jst").collect().height
    return ScanBenchmark(row_count, perf_counter() - started)
