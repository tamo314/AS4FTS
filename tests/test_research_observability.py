import json
from types import SimpleNamespace

import pytest

from n225m_bt.research.observability import strategy_diagnostics, timed_call
from n225m_bt.research.runner import run_family
from n225m_bt.research.space import trials
from test_research_fault_routing import workspace


def test_diagnostics_are_bounded_and_optional():
    assert strategy_diagnostics(object()) == {'available': False}
    result = strategy_diagnostics(SimpleNamespace(diagnostics={i: 'no_night' for i in range(20)}))
    assert result['reason_counts']['no_night'] == 20
    assert len(result['examples']) == 5


def test_timing_is_recorded_on_failure():
    state = {'active': {}}
    with pytest.raises(ValueError):
        timed_call(state, 'implement', lambda: (_ for _ in ()).throw(ValueError('x')))
    assert state['phase_seconds']['implement'] >= 0


def test_unsupported_variant_semantics_are_not_silently_ignored():
    with pytest.raises(ValueError, match='unsupported execution fields'):
        list(trials({'space': {'profile': ['shallow', 'deep']}, 'variants': [
            {'when': {'profile': 'shallow'}, 'derived_parameters': {'min': .25}}]}))
    assert len(list(trials({'space': {'x': [1, 2]}, 'variants': [
        {'constraints': [{'left': 'x', 'op': 'eq', 'right': 2}]}]}))) == 1


def test_post_run_diagnostics_and_engine_counters(tmp_path):
    workspace(tmp_path)
    summary = run_family(tmp_path / 'family.json', tmp_path)
    rows = json.loads((__import__('pathlib').Path(summary['identity']['output']) / 'trials.json').read_text())
    assert all(r['metrics']['eligible_bar_count'] > 0 for r in rows)
    assert all(r['metrics']['entry_signals_returned'] >= r['metrics']['trade_count'] for r in rows)
    assert summary['timing']['invocation_wall_seconds'] > 0
    assert summary['diagnostics_summary']['zero_trade_cases'] >= 0
