from pathlib import Path

from n225m_bt.research.dependencies import dependency_manifest
from n225m_bt.research.datasets import write_json
from n225m_bt.research.runner import run_family
from test_research_fault_routing import workspace


def test_dependency_identity_ignores_unrelated_strategy(tmp_path):
    workspace(tmp_path)
    factory = 'n225m_bt.strategies.range_breakout:create_strategy'
    before = dependency_manifest(tmp_path, factory, {})
    assert before['cacheable'], before
    (tmp_path / 'src/n225m_bt/strategies/unrelated.py').write_text('x = 1')
    assert dependency_manifest(tmp_path, factory, {}) == before
    path = tmp_path / 'src/n225m_bt/components/primitives.py'
    path.write_text(path.read_text() + '\n# changed dependency\n')
    assert dependency_manifest(tmp_path, factory, {}) != before


def test_dynamic_import_disables_reuse(tmp_path):
    workspace(tmp_path)
    path = tmp_path / 'src/n225m_bt/strategies/dynamic.py'
    path.write_text('from importlib import import_module as load\ndef create_strategy(p):\n return load(p["module"])\n')
    result = dependency_manifest(tmp_path, 'n225m_bt.strategies.dynamic:create_strategy', {})
    assert result['cacheable'] is False and result['warnings']


def test_external_parameter_file_is_hashed(tmp_path):
    workspace(tmp_path)
    resource = tmp_path / 'custom.yaml'
    resource.write_text('x: 1')
    spec = {'parameters': {'sessions_path': 'custom.yaml'}}
    first = dependency_manifest(tmp_path, 'n225m_bt.strategies.range_breakout:create_strategy', spec)
    resource.write_text('x: 2')
    assert dependency_manifest(tmp_path, 'n225m_bt.strategies.range_breakout:create_strategy', spec) != first


def test_real_cross_family_cache_survives_unrelated_code(tmp_path):
    workspace(tmp_path)
    first = run_family(tmp_path / 'family.json', tmp_path)
    (tmp_path / 'src/n225m_bt/strategies/unrelated.py').write_text('x = 2')
    import json
    spec = json.loads((tmp_path / 'family.json').read_text())
    spec['family_id'] = 'another_campaign'
    write_json(tmp_path / 'family.json', spec)
    second = run_family(tmp_path / 'family.json', tmp_path)
    assert first['coverage']['cache_hits'] == 0
    assert second['coverage']['cache_hits'] == 2
    changed = tmp_path / 'src/n225m_bt/components/primitives.py'
    changed.write_text(changed.read_text() + '\n# genuinely revised dependency\n')
    third = run_family(tmp_path / 'family.json', tmp_path)
    assert third['coverage']['cache_hits'] == 0
