"""Integer N225M execution-cost and PnL calculations."""

from __future__ import annotations

from n225m_bt.domain import InstrumentSpec, Side


def adverse_fill(
    reference_price: int, is_buy: bool, slippage_ticks: int, spec: InstrumentSpec
) -> int:
    delta = slippage_ticks * spec.tick_size
    return reference_price + delta if is_buy else reference_price - delta


def gross_pnl(entry_fill: int, exit_fill: int, side: Side, qty: int, spec: InstrumentSpec) -> int:
    return (exit_fill - entry_fill) * side.sign * qty * spec.multiplier


def slippage_cost(
    entry_reference: int,
    entry_fill: int,
    exit_reference: int,
    exit_fill: int,
    qty: int,
    spec: InstrumentSpec,
) -> int:
    return (
        (abs(entry_fill - entry_reference) + abs(exit_fill - exit_reference))
        * qty
        * spec.multiplier
    )
