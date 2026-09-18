"""Persist results; reporting only serializes computed economics."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import polars as pl

from n225m_bt.domain import Trade
from n225m_bt.reports.metrics import calculate_metrics
from n225m_bt.reports.segmentation import segmented_metrics


def write_results(
    output_dir: Path,
    trades: tuple[Trade, ...],
    equity: tuple[int, ...],
    manifest: dict[str, object],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [asdict(trade) for trade in trades]
    pl.DataFrame(rows or {"trade_id": []}).write_parquet(output_dir / "trades.parquet")
    order_rows: list[dict[str, object]] = []
    fill_rows: list[dict[str, object]] = []
    for trade in trades:
        order_rows.extend(
            [
                {
                    "trade_id": trade.trade_id,
                    "order_kind": "entry_market",
                    "signal_ts": trade.entry_signal_ts,
                    "fill_ts": trade.entry_ts,
                    "status": "filled",
                },
                {
                    "trade_id": trade.trade_id,
                    "order_kind": f"exit_{trade.exit_reason.value}",
                    "signal_ts": trade.exit_signal_ts,
                    "fill_ts": trade.exit_ts,
                    "status": "filled",
                },
            ]
        )
        fill_rows.extend(
            [
                {
                    "trade_id": trade.trade_id,
                    "fill_kind": "entry",
                    "ts_jst": trade.entry_ts,
                    "reference_price": trade.entry_reference_price,
                    "fill_price": trade.entry_fill_price,
                },
                {
                    "trade_id": trade.trade_id,
                    "fill_kind": "exit",
                    "ts_jst": trade.exit_ts,
                    "reference_price": trade.exit_reference_price,
                    "fill_price": trade.exit_fill_price,
                },
            ]
        )
    pl.DataFrame(order_rows or {"trade_id": []}).write_parquet(output_dir / "orders.parquet")
    pl.DataFrame(fill_rows or {"trade_id": []}).write_parquet(output_dir / "fills.parquet")
    pl.DataFrame(
        {"bar_index": list(range(len(equity))), "realized_equity_jpy": list(equity)}
    ).write_parquet(output_dir / "equity.parquet")
    overall = calculate_metrics(trades)
    metrics: dict[str, object] = {"overall": overall, "segments": segmented_metrics(trades)}
    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8"
    )
    markdown = (
        "# Backtest metrics\n\n"
        + "\n".join(f"- `{key}`: {value}" for key, value in overall.items())
        + "\n"
    )
    (output_dir / "metrics.md").write_text(markdown, encoding="utf-8")
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, default=str, indent=2, sort_keys=True), encoding="utf-8"
    )
