from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from n225m_bt.config import JST
from n225m_bt.domain import Bar, Session, SignalAction
from n225m_bt.research.runner import read_spec
from n225m_bt.research.space import trials
from n225m_bt.strategies.base import StrategyContext
from n225m_bt.strategies.opening_range_failure import create_strategy
from n225m_bt.strategies.opening_range_failure_fade import create_strategy as legacy_factory

ROOT = Path(__file__).parents[1]


def run_points(points, direction="short", legacy=False):
    params = dict(opening_minutes=15, breakout_buffer_fraction=.05, entry_window_minutes=120,
                  reentry_depth_fraction=0, reentry_timeout_minutes=3,
                  stop_fraction=.25, reward_multiple=1, direction=direction,
                  sessions_path=str(ROOT / "config/sessions.yaml"))
    strategy = (legacy_factory if legacy else create_strategy)(params)
    start = datetime(2024, 11, 5, 8, 45, tzinfo=JST)
    bars = [Bar(start + timedelta(minutes=i), date(2024, 11, 5), date(2024, 11, 5),
                Session.DAY, "test", 40000, 40010, 39990, 40000) for i in range(15)]
    for minute, close in points:
        ts = start + timedelta(minutes=15 + minute)
        bars.append(Bar(ts, ts.date(), ts.date(), Session.DAY, "test", close, close, close, close))
    signals = []
    for bar in bars:
        signal = strategy.on_bar(StrategyContext([], False), bar)
        if signal:
            signals.append(signal)
    return signals


@pytest.mark.parametrize("direction,breakout,outside,boundary", [
    ("short", 40015, 39980, 40010), ("long", 39985, 40020, 39990)])
def test_both_bounds_and_boundary_inclusive(direction, breakout, outside, boundary):
    assert run_points([(0, breakout), (1, outside)], direction) == []
    assert len(run_points([(0, breakout), (1, boundary)], direction)) == 1


def test_inclusive_deadline_and_next_event_rearm():
    assert len(run_points([(0, 40015), (3, 40000)])) == 1
    assert run_points([(0, 40015), (4, 40000)]) == []
    assert len(run_points([(0, 40015), (4, 40000), (5, 40015), (6, 40000)])) == 1


def test_monitoring_end_not_shortened_and_end_exclusive():
    assert len(run_points([(118, 40015), (119, 40000)])) == 1
    assert run_points([(119, 40015), (120, 40000)]) == []


def test_same_bar_and_signal_limit():
    assert run_points([(0, 40015), (0, 40000)]) == []
    signals = run_points([(0, 40015), (1, 40000), (5, 40015), (6, 40000)])
    assert len(signals) == 1 and signals[0].action is SignalAction.ENTER_SHORT


def test_legacy_h01_behavior_is_preserved():
    assert len(run_points([(0, 40015), (1, 39980)], legacy=True)) == 1
    assert run_points([(0, 40015), (3, 40000)], legacy=True) == []


def test_h02_full_grid_constructs_without_mutation():
    spec = read_spec(ROOT / "examples/research/h02_contract_v2.yaml")
    cases = list(trials(spec))
    assert len(cases) == 432
    for case in cases:
        params = case["parameters"] | {"sessions_path": str(ROOT / "config/sessions.yaml")}
        before = dict(params)
        assert create_strategy(params).strategy_version == "2"
        assert params == before
