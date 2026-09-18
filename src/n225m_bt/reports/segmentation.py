"""Deterministic trade-ledger segmentation without modifying economics."""

from __future__ import annotations

from collections import defaultdict

from n225m_bt.domain import Trade
from n225m_bt.reports.metrics import calculate_metrics


def segmented_metrics(trades: tuple[Trade, ...]) -> dict[str, dict[str, dict[str, int | float]]]:
    """Return requested V1 ledger cuts, retaining only groups present in the ledger."""
    groups: dict[str, dict[str, list[Trade]]] = {
        "year": defaultdict(list),
        "month": defaultdict(list),
        "weekday": defaultdict(list),
        "session": defaultdict(list),
        "hour": defaultdict(list),
        "roll_risk": defaultdict(list),
    }
    for trade in trades:
        groups["year"][str(trade.trade_date.year)].append(trade)
        groups["month"][trade.trade_date.strftime("%Y-%m")].append(trade)
        groups["weekday"][str(trade.entry_ts.weekday())].append(trade)
        groups["session"][str(trade.metadata.get("entry_session", "unknown"))].append(trade)
        groups["hour"][str(trade.entry_ts.hour)].append(trade)
        groups["roll_risk"][str(bool(trade.metadata.get("entry_roll_risk", False))).lower()].append(
            trade
        )
    return {
        name: {key: calculate_metrics(values) for key, values in sorted(group.items())}
        for name, group in groups.items()
    }
