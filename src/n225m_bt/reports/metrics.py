"""Small deterministic performance metrics over a completed trade ledger."""

from __future__ import annotations

from n225m_bt.domain import Trade


def calculate_metrics(trades: list[Trade] | tuple[Trade, ...]) -> dict[str, int | float]:
    net = [trade.net_pnl_jpy for trade in trades]
    gross = [trade.gross_pnl_jpy for trade in trades]
    wins = [value for value in net if value > 0]
    losses = [value for value in net if value < 0]
    return {
        "trade_count": len(trades),
        "net_pnl_jpy": sum(net),
        "gross_pnl_jpy": sum(gross),
        "fees_jpy": sum(trade.fees_jpy for trade in trades),
        "slippage_cost_jpy": sum(trade.slippage_cost_jpy for trade in trades),
        "win_rate": len(wins) / len(trades) if trades else 0.0,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else 0.0,
    }
