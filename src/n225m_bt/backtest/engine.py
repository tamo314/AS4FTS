"""Deterministic bar-close signal / next-eligible-open execution engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from n225m_bt.backtest.costs import adverse_fill
from n225m_bt.backtest.intrabar import protective_exit
from n225m_bt.backtest.portfolio import Portfolio
from n225m_bt.calendar.classifier import CalendarClassifier
from n225m_bt.config import BacktestConfig
from n225m_bt.domain import (
    Bar, ExitReason, InstrumentSpec, Position, Session, Side, Signal, SignalAction, Trade,
)
from n225m_bt.strategies.base import HistoryView, Strategy, StrategyContext


@dataclass(frozen=True, slots=True)
class PendingOrder:
    signal: Signal
    side: Side | None
    created_session: Session
    created_trade_date: date
    exit_reason: ExitReason | None = None


@dataclass(frozen=True, slots=True)
class BacktestResult:
    trades: tuple[Trade, ...]
    equity: tuple[int, ...]
    canceled_orders: int


class BacktestEngine:
    def __init__(
        self, spec: InstrumentSpec, config: BacktestConfig, classifier: CalendarClassifier
    ) -> None:
        self.spec, self.config, self.classifier = spec, config, classifier

    def run(self, bars: list[Bar], strategy: Strategy, parameter_hash: str = "", *,
            assume_sorted: bool = False) -> BacktestResult:
        """A batch may reuse already sorted immutable bars; strategy state is per run."""
        # Optional runtime binding shares the actual run calendar without adding
        # calendar paths to each parameter point. Older strategies need no hook.
        bind_runtime = getattr(strategy, "bind_runtime", None)
        if callable(bind_runtime):
            bind_runtime(self.classifier)
        ordered = bars if assume_sorted else sorted(bars, key=lambda bar: bar.ts_jst)
        portfolio = Portfolio(
            self.spec, self.config.fees.jpy_per_side_per_contract,
            strategy.strategy_id, strategy.strategy_version, parameter_hash,
        )
        pending: PendingOrder | None = None
        canceled = 0
        history: list[Bar] = []
        history_view = HistoryView(history)
        equity: list[int] = []
        realized = 0
        accounted = 0
        last_eligible: Bar | None = None
        boundaries: dict[tuple[date, Session], tuple[datetime, datetime]] = {}
        for bar in ordered:
            if not bar.is_eligible or not self._mode_allows(bar):
                continue
            last_eligible = bar
            key = (bar.trade_date, bar.session)
            if key not in boundaries:
                close = self.classifier.session_close(*key)
                boundaries[key] = (
                    close - timedelta(minutes=self.config.risk.new_entry_cutoff_minutes_before_session_close),
                    close - timedelta(minutes=self.config.risk.force_flat_minutes_before_session_close),
                )
            entry_cutoff, force_flat = boundaries[key]
            if pending is not None:
                if (
                    not self.config.execution.allow_cross_session_pending_order
                    and (pending.created_trade_date != bar.trade_date
                         or pending.created_session is not bar.session)
                ) or self._delay_exceeded(pending.signal.timestamp, bar.ts_jst) or (
                    pending.side is not None and bar.ts_jst >= entry_cutoff
                ):
                    canceled += 1
                else:
                    self._apply_pending(portfolio, pending, bar)
                pending = None
            if portfolio.position is not None:
                portfolio.update_excursion(bar.high, bar.low)
                protective = protective_exit(portfolio.position, bar)
                if protective is not None:
                    fill = adverse_fill(
                        protective.reference_price, not portfolio.position.side.close_is_sell,
                        self.config.execution.slippage_ticks, self.spec,
                    )
                    portfolio.exit(bar.ts_jst, None, protective.reference_price, fill, protective.reason)
            if (portfolio.position is not None and self.config.risk.force_flat
                    and bar.ts_jst >= force_flat):
                self._force_flat(portfolio, bar)
            history.append(bar)
            # Exit decisions and indicator updates remain available after entry cutoff.
            signal = strategy.on_bar(StrategyContext(history_view, portfolio.position is not None), bar)
            if signal is not None and (signal.action is SignalAction.EXIT or bar.ts_jst < entry_cutoff):
                pending = self._pending_from_signal(signal, bar, portfolio.position is not None)
            for trade in portfolio.trades[accounted:]:
                realized += trade.net_pnl_jpy
            accounted = len(portfolio.trades)
            equity.append(realized)
        if pending is not None:
            canceled += 1
        if portfolio.position is not None and last_eligible is not None:
            fill = adverse_fill(
                last_eligible.close, not portfolio.position.side.close_is_sell,
                self.config.execution.slippage_ticks, self.spec,
            )
            trade = portfolio.exit(last_eligible.ts_jst, None, last_eligible.close, fill, ExitReason.END_OF_DATA)
            realized += trade.net_pnl_jpy
            equity[-1] = realized
        return BacktestResult(tuple(portfolio.trades), tuple(equity), canceled)

    def _apply_pending(self, portfolio: Portfolio, pending: PendingOrder, bar: Bar) -> None:
        if pending.exit_reason is not None:
            if portfolio.position is None:
                return
            fill = adverse_fill(
                bar.open, not portfolio.position.side.close_is_sell,
                self.config.execution.slippage_ticks, self.spec,
            )
            portfolio.exit(bar.ts_jst, pending.signal.timestamp, bar.open, fill, pending.exit_reason)
            return
        if pending.side is None or portfolio.position is not None:
            return
        fill = adverse_fill(bar.open, pending.side is Side.LONG, self.config.execution.slippage_ticks, self.spec)
        portfolio.enter(Position(
            pending.side, 1, bar.ts_jst, pending.signal.timestamp, bar.open, fill,
            bar.trade_date, pending.signal.stop_price, pending.signal.target_price,
            entry_reason=pending.signal.reason, entry_session=bar.session, entry_roll_risk=bar.roll_risk,
        ))

    def _force_flat(self, portfolio: Portfolio, bar: Bar) -> None:
        """Risk policy exit at the current eligible bar close."""
        assert portfolio.position is not None
        fill = adverse_fill(bar.close, not portfolio.position.side.close_is_sell,
                            self.config.execution.slippage_ticks, self.spec)
        portfolio.exit(bar.ts_jst, bar.ts_jst, bar.close, fill, ExitReason.FORCE_FLAT)

    def _pending_from_signal(self, signal: Signal, bar: Bar, has_position: bool) -> PendingOrder | None:
        if signal.action is SignalAction.EXIT:
            return (PendingOrder(signal, None, bar.session, bar.trade_date, ExitReason.SIGNAL)
                    if has_position else None)
        if has_position:
            return None
        side = Side.LONG if signal.action is SignalAction.ENTER_LONG else Side.SHORT
        return PendingOrder(signal, side, bar.session, bar.trade_date)

    def _mode_allows(self, bar: Bar) -> bool:
        return self.config.mode == "full_session" or self.config.mode == f"{bar.session.value}_only"

    def _delay_exceeded(self, source: datetime, current: datetime) -> bool:
        return current - source > timedelta(minutes=self.config.execution.max_fill_delay_minutes)

    def _entry_cutoff(self, bar: Bar) -> bool:
        close = self.classifier.session_close(bar.trade_date, bar.session)
        return bar.ts_jst >= close - timedelta(minutes=self.config.risk.new_entry_cutoff_minutes_before_session_close)

    def _at_force_flat(self, bar: Bar) -> bool:
        close = self.classifier.session_close(bar.trade_date, bar.session)
        return bar.ts_jst >= close - timedelta(minutes=self.config.risk.force_flat_minutes_before_session_close)
