"""Single-position state and trade-ledger construction."""

from __future__ import annotations

from datetime import datetime

from n225m_bt.backtest.costs import gross_pnl, slippage_cost
from n225m_bt.domain import ExitReason, InstrumentSpec, Position, Side, Trade


class Portfolio:
    def __init__(
        self,
        spec: InstrumentSpec,
        fee_per_side: int,
        strategy_id: str,
        strategy_version: str,
        parameter_hash: str,
    ) -> None:
        self.spec = spec
        self.fee_per_side = fee_per_side
        self.strategy_id = strategy_id
        self.strategy_version = strategy_version
        self.parameter_hash = parameter_hash
        self.position: Position | None = None
        self.trades: list[Trade] = []

    def enter(self, position: Position) -> None:
        if self.position is not None:
            raise ValueError("V1 forbids pyramiding and simultaneous positions")
        self.position = position

    def update_excursion(self, high: int, low: int) -> None:
        if self.position is None:
            return
        position = self.position
        if position.side is Side.LONG:
            position.mae_price_delta = max(
                position.mae_price_delta, position.entry_fill_price - low
            )
            position.mfe_price_delta = max(
                position.mfe_price_delta, high - position.entry_fill_price
            )
        else:
            position.mae_price_delta = max(
                position.mae_price_delta, high - position.entry_fill_price
            )
            position.mfe_price_delta = max(
                position.mfe_price_delta, position.entry_fill_price - low
            )

    def exit(
        self,
        ts: datetime,
        signal_ts: datetime | None,
        reference: int,
        fill: int,
        reason: ExitReason,
    ) -> Trade:
        if self.position is None:
            raise ValueError("cannot exit when flat")
        position = self.position
        fees = 2 * self.fee_per_side * position.qty
        gross = gross_pnl(position.entry_fill_price, fill, position.side, position.qty, self.spec)
        slip = slippage_cost(
            position.entry_reference_price,
            position.entry_fill_price,
            reference,
            fill,
            position.qty,
            self.spec,
        )
        trade = Trade(
            trade_id=f"trade-{len(self.trades) + 1:06d}",
            trade_date=position.trade_date,
            side=position.side,
            qty=position.qty,
            entry_signal_ts=position.entry_signal_ts,
            entry_ts=position.entry_ts,
            entry_reference_price=position.entry_reference_price,
            entry_fill_price=position.entry_fill_price,
            exit_signal_ts=signal_ts,
            exit_ts=ts,
            exit_reference_price=reference,
            exit_fill_price=fill,
            gross_pnl_jpy=gross,
            fees_jpy=fees,
            slippage_cost_jpy=slip,
            net_pnl_jpy=gross - fees,
            mae_jpy=position.mae_price_delta * position.qty * self.spec.multiplier,
            mfe_jpy=position.mfe_price_delta * position.qty * self.spec.multiplier,
            holding_minutes=int((ts - position.entry_ts).total_seconds() // 60),
            entry_reason=position.entry_reason,
            exit_reason=reason,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            parameter_hash=self.parameter_hash,
            metadata={
                "entry_session": position.entry_session.value
                if position.entry_session is not None
                else "unknown",
                "entry_roll_risk": position.entry_roll_risk,
            },
        )
        self.trades.append(trade)
        self.position = None
        return trade
