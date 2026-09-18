"""Explicit friction sensitivity runs over identical bars, configuration, and strategy."""

from __future__ import annotations

from n225m_bt.backtest.engine import BacktestEngine
from n225m_bt.calendar.classifier import CalendarClassifier
from n225m_bt.config import BacktestConfig
from n225m_bt.domain import Bar, InstrumentSpec
from n225m_bt.reports.metrics import calculate_metrics
from n225m_bt.strategies.base import Strategy


def slippage_sweep(
    spec: InstrumentSpec,
    config: BacktestConfig,
    classifier: CalendarClassifier,
    bars: list[Bar],
    strategy: Strategy,
    parameter_hash: str = "",
) -> dict[int, dict[str, int | float]]:
    """Run configured tick scenarios independently; original configuration remains unchanged."""
    results: dict[int, dict[str, int | float]] = {}
    for ticks in config.reporting.slippage_stress_ticks:
        execution = config.execution.model_copy(update={"slippage_ticks": ticks})
        scenario = config.model_copy(update={"execution": execution})
        result = BacktestEngine(spec, scenario, classifier).run(bars, strategy, parameter_hash)
        results[ticks] = calculate_metrics(result.trades)
    return results
