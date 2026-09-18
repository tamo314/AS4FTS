from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import polars as pl

from n225m_bt.config import JST
from n225m_bt.domain import ExitReason, Side, Trade
from n225m_bt.reports.writer import write_results


def sample_trade() -> Trade:
    entry = datetime(2024, 11, 5, 9, 1, tzinfo=JST)
    exit_ = datetime(2024, 11, 5, 9, 2, tzinfo=JST)
    return Trade(
        "trade-000001",
        date(2024, 11, 5),
        Side.LONG,
        1,
        datetime(2024, 11, 5, 9, 0, tzinfo=JST),
        entry,
        40000,
        40005,
        None,
        exit_,
        40000,
        39995,
        -1000,
        200,
        1000,
        -1200,
        0,
        0,
        1,
        "signal",
        ExitReason.SIGNAL,
        "test",
        "1",
        "",
        {"entry_session": "day", "entry_roll_risk": False},
    )


def test_writer_emits_ledger_files_and_segments(workspace_tmp: Path) -> None:
    output = workspace_tmp / "results"
    write_results(output, (sample_trade(),), (0, -1200), {"dataset_id": "test"})
    assert pl.read_parquet(output / "trades.parquet").height == 1
    assert pl.read_parquet(output / "orders.parquet").height == 2
    assert pl.read_parquet(output / "fills.parquet").height == 2
    metrics = json.loads((output / "metrics.json").read_text())
    assert metrics["overall"]["net_pnl_jpy"] == -1200
    assert metrics["segments"]["session"]["day"]["trade_count"] == 1
