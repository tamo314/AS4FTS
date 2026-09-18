from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from n225m_bt.backtest.costs import adverse_fill, gross_pnl
from n225m_bt.backtest.engine import BacktestEngine
from n225m_bt.config import JST
from n225m_bt.domain import Bar, ExitReason, Session, Side, Signal, SignalAction
from n225m_bt.reports.sweep import slippage_sweep
from n225m_bt.strategies.base import StrategyContext
from n225m_bt.strategies.examples import AlwaysFlatStrategy


@dataclass(frozen=True)
class OneSignal:
    timestamp: datetime
    signal: Signal
    strategy_id: str = "one_signal"
    strategy_version: str = "1"

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> Signal | None:
        return self.signal if bar.ts_jst == self.timestamp else None


@dataclass(frozen=True)
class ScriptedSignals:
    signals: dict[datetime, Signal]
    strategy_id: str = "scripted_signals"
    strategy_version: str = "1"

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> Signal | None:
        return self.signals.get(bar.ts_jst)


@dataclass
class HistoryInspectingStrategy:
    history_ids: list[int]
    history_lengths: list[int]
    strategy_id: str = "history_inspecting"
    strategy_version: str = "1"

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> Signal | None:
        self.history_ids.append(id(ctx.history))
        self.history_lengths.append(len(ctx.history))
        return None


def bar(hour: int, minute: int, *, open_: int, high: int, low: int, close: int) -> Bar:
    ts = datetime(2024, 11, 5, hour, minute, tzinfo=JST)
    return Bar(
        ts,
        date(2024, 11, 5),
        ts.date(),
        Session.DAY,
        "ose_n225m_from_20241105",
        open_,
        high,
        low,
        close,
    )


def dated_bar(
    trade_date: date,
    hour: int,
    minute: int,
    session: Session = Session.DAY,
    *,
    open_: int = 40000,
    high: int = 40005,
    low: int = 39995,
    close: int = 40000,
) -> Bar:
    ts = datetime(trade_date.year, trade_date.month, trade_date.day, hour, minute, tzinfo=JST)
    return Bar(ts, trade_date, ts.date(), session, "test", open_, high, low, close)


def test_tick_economics_and_adverse_slippage(
    project_config: tuple[object, object, object, object],
) -> None:
    spec = project_config[0].instrument.to_spec()  # type: ignore[attr-defined]
    assert gross_pnl(40000, 40005, Side.LONG, 1, spec) == 500
    assert gross_pnl(40000, 39995, Side.SHORT, 1, spec) == 500
    assert adverse_fill(40000, True, 1, spec) == 40005
    assert adverse_fill(40000, False, 1, spec) == 39995


def test_next_bar_fill_and_conservative_stop_target(
    classifier: object, project_config: tuple[object, object, object, object]
) -> None:
    spec, _, _, config = project_config
    first = bar(9, 0, open_=40000, high=40010, low=39990, close=40000)
    second = bar(9, 1, open_=40000, high=40120, low=39940, close=40000)
    third = bar(9, 2, open_=40000, high=40005, low=39995, close=40000)
    signal = Signal(SignalAction.ENTER_LONG, first.ts_jst, stop_price=39950, target_price=40100)
    result = BacktestEngine(spec.instrument.to_spec(), config, classifier).run(
        [first, second, third], OneSignal(first.ts_jst, signal)
    )  # type: ignore[attr-defined,arg-type]
    trade = result.trades[0]
    assert trade.entry_ts == second.ts_jst
    assert trade.exit_reason is ExitReason.STOP
    assert trade.exit_reference_price == 39950
    assert trade.exit_fill_price == 39945
    assert trade.net_pnl_jpy == trade.gross_pnl_jpy - trade.fees_jpy


def test_gap_through_stop_uses_open(
    classifier: object, project_config: tuple[object, object, object, object]
) -> None:
    spec, _, _, config = project_config
    first = bar(9, 0, open_=40000, high=40005, low=39995, close=40000)
    entry = bar(9, 1, open_=40000, high=40005, low=39995, close=40000)
    gap = bar(9, 2, open_=39920, high=39940, low=39900, close=39920)
    signal = Signal(SignalAction.ENTER_LONG, first.ts_jst, stop_price=39950)
    result = BacktestEngine(spec.instrument.to_spec(), config, classifier).run(
        [first, entry, gap], OneSignal(first.ts_jst, signal)
    )  # type: ignore[attr-defined,arg-type]
    assert result.trades[0].exit_reference_price == 39920


def test_short_same_bar_stop_target_uses_adverse_stop(
    classifier: object, project_config: tuple[object, object, object, object]
) -> None:
    spec, _, _, config = project_config
    first = bar(9, 0, open_=40000, high=40005, low=39995, close=40000)
    second = bar(9, 1, open_=40000, high=40060, low=39880, close=40000)
    signal = Signal(SignalAction.ENTER_SHORT, first.ts_jst, stop_price=40050, target_price=39900)
    result = BacktestEngine(spec.instrument.to_spec(), config, classifier).run(
        [first, second], OneSignal(first.ts_jst, signal)
    )  # type: ignore[attr-defined,arg-type]
    assert result.trades[0].exit_reason is ExitReason.STOP
    assert result.trades[0].exit_fill_price == 40055


def test_forced_flat_uses_relative_historical_session_close(
    classifier: object, project_config: tuple[object, object, object, object]
) -> None:
    spec, _, _, config = project_config
    for trade_date, force_hour, force_minute in [
        (date(2021, 9, 21), 15, 10),
        (date(2024, 11, 5), 15, 40),
    ]:
        signal_bar = dated_bar(trade_date, 14, 58)
        entry_bar = dated_bar(trade_date, 14, 59)
        forced_bar = dated_bar(trade_date, force_hour, force_minute)
        result = BacktestEngine(spec.instrument.to_spec(), config, classifier).run(
            [signal_bar, entry_bar, forced_bar],
            OneSignal(signal_bar.ts_jst, Signal(SignalAction.ENTER_LONG, signal_bar.ts_jst)),
        )  # type: ignore[attr-defined,arg-type]
        assert result.trades[0].exit_reason is ExitReason.FORCE_FLAT
        assert result.trades[0].exit_ts == forced_bar.ts_jst


def test_pending_order_does_not_cross_session(
    classifier: object, project_config: tuple[object, object, object, object]
) -> None:
    spec, _, _, config = project_config
    execution = config.execution.model_copy(update={"max_fill_delay_minutes": 200})  # type: ignore[attr-defined]
    risk = config.risk.model_copy(update={"new_entry_cutoff_minutes_before_session_close": 0})  # type: ignore[attr-defined]
    config = config.model_copy(update={"execution": execution, "risk": risk})  # type: ignore[attr-defined]
    trade_date = date(2021, 9, 21)
    signal_bar = dated_bar(trade_date, 15, 14)
    night_bar = dated_bar(trade_date, 16, 30, Session.NIGHT)
    result = BacktestEngine(spec.instrument.to_spec(), config, classifier).run(
        [signal_bar, night_bar],
        OneSignal(signal_bar.ts_jst, Signal(SignalAction.ENTER_LONG, signal_bar.ts_jst)),
    )  # type: ignore[attr-defined,arg-type]
    assert result.trades == ()
    assert result.canceled_orders == 1


def test_no_pyramiding_and_fees_are_explicit(
    classifier: object, project_config: tuple[object, object, object, object]
) -> None:
    spec, _, _, config = project_config
    fees = config.fees.model_copy(update={"jpy_per_side_per_contract": 100})  # type: ignore[attr-defined]
    config = config.model_copy(update={"fees": fees})  # type: ignore[attr-defined]
    first = bar(9, 0, open_=40000, high=40005, low=39995, close=40000)
    second = bar(9, 1, open_=40000, high=40005, low=39995, close=40000)
    third = bar(9, 2, open_=40000, high=40005, low=39995, close=40000)
    strategy = ScriptedSignals(
        {
            first.ts_jst: Signal(SignalAction.ENTER_LONG, first.ts_jst),
            second.ts_jst: Signal(SignalAction.ENTER_LONG, second.ts_jst),
        }
    )
    result = BacktestEngine(spec.instrument.to_spec(), config, classifier).run(
        [first, second, third], strategy
    )  # type: ignore[attr-defined,arg-type]
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.fees_jpy == 200
    assert trade.net_pnl_jpy == trade.gross_pnl_jpy - 200


def test_baseline_always_flat_and_slippage_sweep(
    classifier: object, project_config: tuple[object, object, object, object]
) -> None:
    spec, _, _, config = project_config
    first = bar(9, 0, open_=40000, high=40005, low=39995, close=40000)
    second = bar(9, 1, open_=40000, high=40005, low=39995, close=40000)
    third = bar(9, 2, open_=40000, high=40005, low=39995, close=40000)
    engine = BacktestEngine(spec.instrument.to_spec(), config, classifier)  # type: ignore[attr-defined,arg-type]
    assert engine.run([first, second, third], AlwaysFlatStrategy()).trades == ()
    strategy = OneSignal(first.ts_jst, Signal(SignalAction.ENTER_LONG, first.ts_jst))
    sweep = slippage_sweep(
        spec.instrument.to_spec(),  # type: ignore[attr-defined]
        config,
        classifier,  # type: ignore[arg-type]
        [first, second, third],
        strategy,
    )
    assert set(sweep) == {0, 1, 2, 3}
    assert sweep[3]["net_pnl_jpy"] < sweep[0]["net_pnl_jpy"]


def test_repeated_deterministic_run_has_identical_ledger(
    classifier: object, project_config: tuple[object, object, object, object]
) -> None:
    spec, _, _, config = project_config
    first = bar(9, 0, open_=40000, high=40005, low=39995, close=40000)
    second = bar(9, 1, open_=40000, high=40005, low=39995, close=40000)
    strategy = OneSignal(first.ts_jst, Signal(SignalAction.ENTER_LONG, first.ts_jst))
    engine = BacktestEngine(spec.instrument.to_spec(), config, classifier)  # type: ignore[attr-defined,arg-type]
    assert (
        engine.run([first, second], strategy).trades == engine.run([first, second], strategy).trades
    )


def test_strategy_history_is_causal_and_reuses_its_read_only_view(
    classifier: object, project_config: tuple[object, object, object, object]
) -> None:
    spec, _, _, config = project_config
    bars = [
        bar(9, 0, open_=40000, high=40005, low=39995, close=40000),
        bar(9, 1, open_=40000, high=40005, low=39995, close=40000),
        bar(9, 2, open_=40000, high=40005, low=39995, close=40000),
    ]
    strategy = HistoryInspectingStrategy([], [])
    BacktestEngine(spec.instrument.to_spec(), config, classifier).run(bars, strategy)  # type: ignore[attr-defined,arg-type]
    assert strategy.history_lengths == [1, 2, 3]
    assert len(set(strategy.history_ids)) == 1
