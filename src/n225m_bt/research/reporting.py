"""Full-space evidence, not just the winning parameter combination."""
from __future__ import annotations

import csv
import itertools
from collections import defaultdict
from pathlib import Path
from statistics import fmean, median
from typing import Any

from n225m_bt.domain import Trade
from n225m_bt.research.datasets import write_json
from n225m_bt.research.space import canonical


def trade_metrics(trades: tuple[Trade, ...]) -> dict[str, Any]:
    net = [trade.net_pnl_jpy for trade in trades]
    wins, losses = [n for n in net if n > 0], [n for n in net if n < 0]
    equity = peak = drawdown = 0
    months: dict[str, int] = defaultdict(int)
    for trade in trades:
        equity += trade.net_pnl_jpy
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
        months[trade.exit_ts.strftime("%Y-%m")] += trade.net_pnl_jpy
    return {"trade_count": len(net), "net_pnl_jpy": sum(net),
            "gross_pnl_jpy": sum(t.gross_pnl_jpy for t in trades),
            "fees_jpy": sum(t.fees_jpy for t in trades),
            "slippage_cost_jpy": sum(t.slippage_cost_jpy for t in trades),
            "win_rate": len(wins) / len(net) if net else 0.0,
            "expectancy_jpy": fmean(net) if net else 0.0,
            "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
            "realized_max_drawdown_jpy": drawdown,
            "monthly_net_pnl_jpy": dict(sorted(months.items())),
            "warnings": (["NO_TRADES"] if not net else []) +
                        (["PROFIT_FACTOR_UNDEFINED_NO_LOSSES"] if not losses else [])}


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [r["metrics"]["net_pnl_jpy"] for r in rows if r["status"] == "ok"]
    return {"attempted": len(rows), "successful": len(values),
            "failed": sum(r["status"] == "failed" for r in rows),
            "positive_fraction": sum(v > 0 for v in values) / len(values) if values else None,
            "mean_net_pnl_jpy": fmean(values) if values else None,
            "median_net_pnl_jpy": median(values) if values else None,
            "min_net_pnl_jpy": min(values) if values else None,
            "max_net_pnl_jpy": max(values) if values else None}


def _flat_point(row: dict[str, Any]) -> dict[str, Any]:
    return row["parameters"] | {f"bt.{k}": v for k, v in row["backtest"].items()} | {"period": row.get("period", "explore")}


def write_report(output: Path, rows: list[dict[str, Any]], planned: int,
                 identity: dict[str, Any]) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    axes = sorted({k for row in rows for k in _flat_point(row)})
    scalar_metrics = sorted({k for row in rows for k, v in row.get("metrics", {}).items()
                             if not isinstance(v, (dict, list))})
    with (output / "trials.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        names = ["trial_id", "status", "cache_hit", "error", "elapsed_seconds"] + [f"param.{a}" for a in axes] + scalar_metrics
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        for row in rows:
            record = {k: row.get(k) for k in names if k in row}
            record.update({f"param.{k}": canonical(v) for k, v in _flat_point(row).items()})
            record.update({k: row.get("metrics", {}).get(k) for k in scalar_metrics})
            writer.writerow(record)
    marginal: dict[str, Any] = {}
    pairwise: dict[str, Any] = {}
    for axis in axes:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            point = _flat_point(row)
            if axis in point:
                groups[canonical(point[axis])].append(row)
        marginal[axis] = {value: _stats(group) for value, group in sorted(groups.items())}
    # Pairwise cells retain interactions without assuming numeric/categorical order.
    varying = [axis for axis in axes if len(marginal[axis]) > 1]
    for left, right in itertools.combinations(varying, 2):
        cells: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            point = _flat_point(row)
            if left in point and right in point:
                cells[canonical([point[left], point[right]])].append(row)
        pairwise[f"{left} | {right}"] = {cell: _stats(group) for cell, group in sorted(cells.items())}
    coverage = {"planned": planned, "attempted": len(rows),
                "successful": sum(r["status"] == "ok" for r in rows),
                "failed": sum(r["status"] == "failed" for r in rows),
                "remaining": planned - len(rows),
                "cache_hits": sum(bool(r.get("cache_hit")) for r in rows)}
    summary = {"identity": identity, "coverage": coverage,
               "status": ("complete_with_failures" if coverage["failed"] else "complete") if len(rows) == planned else "partial",
               "distribution": _stats(rows), "marginal": marginal,
               "note": "Exploratory full-space evidence; not independent out-of-sample confirmation."}
    summary["diagnostics_summary"] = {
        "zero_trade_cases": sum(r["status"] == "ok" and r.get("metrics", {}).get("trade_count") == 0 for r in rows),
        "diagnostics_available_cases": sum(r.get("diagnostics", {}).get("available", False) for r in rows),
        "note": "Zero trades are reported, not classified as strategy failure or rejection."}
    write_json(output / "diagnostics.json", [{"trial_id": r["trial_id"],
               "diagnostics": r.get("diagnostics", {"available": False}),
               "entry_signals_returned": r.get("metrics", {}).get("entry_signals_returned"),
               "canceled_orders": r.get("metrics", {}).get("canceled_orders")} for r in rows])
    write_json(output / "summary.json", summary)
    write_json(output / "sensitivity.json", {"marginal": marginal, "pairwise": pairwise})
    write_json(output / "trials.json", rows)
    write_json(output / "failures.json", [r for r in rows if r["status"] == "failed"])
    write_json(output / "monthly.json", [{"trial_id": r["trial_id"],
                "parameters": r["parameters"], "backtest": r["backtest"], "period": r.get("period"),
                "monthly_net_pnl_jpy": r.get("metrics", {}).get("monthly_net_pnl_jpy", {})}
                for r in rows])
    (output / "summary.md").write_text(
        f"# {identity['family_id']}\n\nStatus: {summary['status']}\n\n"
        f"Planned: {planned}; attempted: {len(rows)}; successful: {coverage['successful']}; "
        f"failed: {coverage['failed']}; remaining: {coverage['remaining']}.\n\n"
        "All results: trials.csv / trials.json. Interactions: sensitivity.json.\n"
        "Drawdown is realized-PnL based. This is exploration, not independent confirmation.\n",
        encoding="utf-8")
    return summary
