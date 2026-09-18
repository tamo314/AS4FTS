from __future__ import annotations

import csv
import gzip
import json
import shutil
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from n225m_bt.backtest.engine import BacktestEngine
from n225m_bt.calendar.classifier import CalendarClassifier
from n225m_bt.config import BacktestConfig, InstrumentConfig, JST, SessionsConfig, load_yaml_model
from n225m_bt.domain import ExitReason, SignalAction
from n225m_bt.research.datasets import register_dataset, synthetic_bars, write_json
from n225m_bt.research.runner import run_family
from n225m_bt.strategies.examples import TimestampSignalStrategy

ROOT = Path(__file__).parents[1]


@pytest.fixture
def workspace(tmp_path):
    shutil.copytree(ROOT / "src", tmp_path / "src", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "config", tmp_path / "config")
    register_dataset(tmp_path, "demo", synthetic_days=2)
    spec = yaml.safe_load((ROOT / "examples/research/breakout.yaml").read_text())
    write_json(tmp_path / "family.json", spec)
    return tmp_path


def test_all_48_cases_and_complete_parameter_reports(workspace):
    summary = run_family(workspace / "family.json", workspace, workers=2)
    assert summary["status"] == "complete", summary
    assert summary["coverage"] == {"planned": 48, "attempted": 48, "successful": 48,
                                    "failed": 0, "remaining": 0, "cache_hits": 0}
    output = Path(summary["identity"]["output"])
    with (output / "trials.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 48
    assert {r["param.lookback"] for r in rows} == {"3", "5", "8"}
    assert all("realized_max_drawdown_jpy" in row for row in rows)
    detail = json.loads((output / "trials.json").read_text())
    assert all(Path(r["trades_path"]).exists() for r in detail)
    for result in detail:
        with gzip.open(result["trades_path"], "rt") as handle:
            trades = [json.loads(line) for line in handle]
        assert sum(t["net_pnl_jpy"] for t in trades) == result["metrics"]["net_pnl_jpy"]
    assert json.loads((output / "sensitivity.json").read_text())["pairwise"]
    repeated = run_family(workspace / "family.json", workspace)
    assert repeated["coverage"]["cache_hits"] == 48


def test_pause_resume_and_reuse_when_space_expands(workspace):
    first = run_family(workspace / "family.json", workspace, max_new_trials=5)
    assert first["status"] == "partial"
    assert first["coverage"]["remaining"] == 43
    second = run_family(workspace / "family.json", workspace)
    assert second["status"] == "complete"
    assert second["coverage"]["cache_hits"] == 5
    spec = json.loads((workspace / "family.json").read_text())
    spec["space"]["lookback"].append(10)
    write_json(workspace / "family.json", spec)
    larger = run_family(workspace / "family.json", workspace)
    assert larger["coverage"]["planned"] == 64
    assert larger["coverage"]["cache_hits"] == 48


def test_parameter_failure_is_recorded_without_stopping_other_cases(workspace):
    spec = json.loads((workspace / "family.json").read_text())
    spec["space"] = {"lookback": [0, 3], "stop_ticks": [2], "target_ticks": [4]}
    spec["backtest_space"] = {}
    write_json(workspace / "family.json", spec)
    summary = run_family(workspace / "family.json", workspace)
    assert summary["status"] == "complete_with_failures"
    assert summary["coverage"]["failed"] == summary["coverage"]["successful"] == 1
    failures = json.loads((Path(summary["identity"]["output"]) / "failures.json").read_text())
    assert failures[0]["parameters"]["lookback"] == 0


def test_changed_source_invalidates_cache_and_separate_periods(workspace):
    spec = json.loads((workspace / "family.json").read_text())
    spec["space"] = {"lookback": [3], "stop_ticks": [2], "target_ticks": [4]}
    spec["backtest_space"] = {}
    spec["periods"] = {"a": {"start": "2024-11-05", "end": "2024-11-05"},
                       "b": {"start": "2024-11-06", "end": "2024-11-06"}}
    write_json(workspace / "family.json", spec)
    initial = run_family(workspace / "family.json", workspace)
    assert initial["coverage"]["successful"] == 2
    with (workspace / "src/n225m_bt/components/primitives.py").open("a") as handle:
        handle.write("\n# next shared version\n")
    changed = run_family(workspace / "family.json", workspace)
    assert changed["coverage"]["cache_hits"] == 0
    assert changed["identity"]["batch_id"] != initial["identity"]["batch_id"]


def test_engine_terminal_equity_uses_last_eligible_bar():
    config = load_yaml_model(ROOT / "config/backtest.yaml", BacktestConfig)
    config = config.model_copy(update={"mode": "day_only"})
    spec = load_yaml_model(ROOT / "config/instrument.yaml", InstrumentConfig).instrument.to_spec()
    sessions = load_yaml_model(ROOT / "config/sessions.yaml", SessionsConfig)
    bars = synthetic_bars(1)[:3]
    invalid = replace(bars[-1], ts_jst=bars[-1].ts_jst.replace(minute=3), close=50000, is_eligible=False)
    strategy = TimestampSignalStrategy({bars[0].ts_jst: SignalAction.ENTER_LONG})
    result = BacktestEngine(spec, config, CalendarClassifier(sessions)).run(bars + [invalid], strategy)
    assert result.trades[-1].exit_ts == bars[-1].ts_jst
    assert result.equity[-1] == sum(t.net_pnl_jpy for t in result.trades)


def test_exit_signal_is_available_after_entry_cutoff():
    config = load_yaml_model(ROOT / "config/backtest.yaml", BacktestConfig)
    config = config.model_copy(update={"risk": config.risk.model_copy(update={"force_flat": False})})
    spec = load_yaml_model(ROOT / "config/instrument.yaml", InstrumentConfig).instrument.to_spec()
    sessions = load_yaml_model(ROOT / "config/sessions.yaml", SessionsConfig)
    source = synthetic_bars(1)[0]
    times = [(15, 27), (15, 28), (15, 31), (15, 32)]
    bars = [replace(source, ts_jst=datetime(2024, 11, 5, h, m, tzinfo=JST)) for h, m in times]
    strategy = TimestampSignalStrategy({bars[0].ts_jst: SignalAction.ENTER_LONG,
                                       bars[2].ts_jst: SignalAction.EXIT})
    result = BacktestEngine(spec, config, CalendarClassifier(sessions)).run(bars, strategy)
    assert result.trades[-1].exit_reason is ExitReason.SIGNAL
    assert result.trades[-1].exit_ts == bars[-1].ts_jst
