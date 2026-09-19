import json
import shutil
import sys
from pathlib import Path

import pytest

from n225m_bt.research import controller
from n225m_bt.research.agent_output import AgentOutputError
from n225m_bt.research.agents import invoke_role, run_process
from n225m_bt.research.datasets import register_dataset, write_json
from n225m_bt.research.runner import run_family
from n225m_bt.research.storage import atomic_text

ROOT = Path(__file__).parents[1]


def workspace(tmp_path):
    for name in ('src', 'config', 'prompts'):
        shutil.copytree(ROOT / name, tmp_path / name, ignore=shutil.ignore_patterns('__pycache__'))
    spec = {"family_id": "trial", "factory": "n225m_bt.strategies.range_breakout:create_strategy",
            "implementation_required": False, "dataset": "demo", "space": {
                "lookback": [3, 5], "stop_ticks": [2], "target_ticks": [4]},
            "backtest": {"mode": "day_only"}}
    write_json(tmp_path / 'family.json', spec)
    config = {"campaign_id": "case", "dataset": "demo", "initial_family": "family.json",
              "max_families": 1, "max_repairs": 0, "roles": {"designer": {}, "implementer": {}}}
    write_json(tmp_path / 'loop.json', config)
    register_dataset(tmp_path, 'demo', synthetic_days=1)
    return config


def test_atomic_permission_retry_preserves_old_file(tmp_path, monkeypatch):
    path = tmp_path / 'a.json'
    path.write_text('old')
    original = Path.replace
    calls = []
    def locked(self, target):
        calls.append(1)
        if len(calls) < 3:
            assert path.read_text() == 'old'
            raise PermissionError('temporary lock')
        return original(self, target)
    monkeypatch.setattr(Path, 'replace', locked)
    monkeypatch.setattr('n225m_bt.research.storage.time.sleep', lambda _: None)
    atomic_text(path, 'new')
    assert path.read_text() == 'new' and len(calls) == 3


def test_permanent_lock_is_not_strategy_error(tmp_path, monkeypatch):
    from n225m_bt.research.faults import fault_record
    path = tmp_path / 'a.json'
    path.write_text('old')
    monkeypatch.setattr(Path, 'replace', lambda *args: (_ for _ in ()).throw(PermissionError('locked')))
    monkeypatch.setattr('n225m_bt.research.storage.time.sleep', lambda _: None)
    with pytest.raises(PermissionError) as error:
        atomic_text(path, 'new', attempts=2)
    assert fault_record(error.value)['kind'] == 'io'
    assert path.read_text() == 'old'


def test_cli_uses_utf8_and_resolved_path(tmp_path):
    rc = run_process([sys.executable, '-c', 'import os;print(os.environ["PYTHONIOENCODING"]);print("日本語")'],
                     tmp_path, tmp_path / 'out', tmp_path / 'err')
    assert rc == 0 and '日本語' in (tmp_path / 'out').read_text(encoding='utf-8')
    assert json.loads((tmp_path / 'out.process.json').read_text())['cwd'] == str(tmp_path)


def test_saved_cli_output_can_be_redecoded_without_another_call(tmp_path):
    script = tmp_path / 'once.py'
    script.write_text('print("bad JSON")')
    role = {'argv': [sys.executable, str(script)], 'stdin': True}
    folder = tmp_path / 'call'
    with pytest.raises(AgentOutputError):
        invoke_role(role, 'test', tmp_path, folder)
    script.unlink()
    (folder / 'output.json').write_text('{"files": []}')
    assert invoke_role(role, 'test', tmp_path, folder) == {'files': []}
    assert json.loads((folder / 'response.json').read_text())['recovered_saved_output']


def test_io_failure_pauses_exact_stage_without_implementer(tmp_path, monkeypatch):
    workspace(tmp_path)
    monkeypatch.setattr(controller, 'invoke_role', lambda *a, **k: pytest.fail('must not call AI'))
    monkeypatch.setattr(controller, 'run_process', lambda *a, **k: (_ for _ in ()).throw(PermissionError('locked')))
    state = controller.run_campaign(tmp_path / 'loop.json', tmp_path)
    assert state['status'] == 'paused_io' and state['active']['stage'] == 'backtest'
    assert state['active']['repairs'] == 0 and state['history'] == []
    def success(argv, root, stdout, stderr, **kw):
        write_json(stdout, {'status': 'complete', 'identity': {'output': str(tmp_path / 'batch')},
                            'coverage': {'successful': 2, 'failed': 0, 'remaining': 0}})
        return 0
    monkeypatch.setattr(controller, 'run_process', success)
    assert controller.run_campaign(tmp_path / 'loop.json', tmp_path)['status'] == 'complete'


def test_strategy_failure_is_not_reported_as_complete(tmp_path, monkeypatch):
    workspace(tmp_path)
    def failed(argv, root, stdout, stderr, **kw):
        write_json(stdout, {'status': 'complete_with_failures', 'failure_kinds': ['strategy'],
            'failure_examples': [{'error': 'broken code'}], 'identity': {'output': str(tmp_path)},
            'coverage': {'successful': 0, 'failed': 2, 'remaining': 0}})
        return 0
    monkeypatch.setattr(controller, 'run_process', failed)
    state = controller.run_campaign(tmp_path / 'loop.json', tmp_path)
    assert state['status'] == 'failed' and state['history'][0]['status'] == 'failed'


def test_original_worker_initialization_error_is_preserved(tmp_path):
    workspace(tmp_path)
    spec = json.loads((tmp_path / 'family.json').read_text())
    spec['periods'] = {'empty': {'start': '2000-01-01', 'end': '2000-01-02'}}
    write_json(tmp_path / 'family.json', spec)
    result = run_family(tmp_path / 'family.json', tmp_path)
    assert result['status'] == 'blocked'
    assert result['execution_fault']['kind'] == 'configuration'
    assert 'no bars' in result['execution_fault']['error']
    assert 'BrokenProcessPool' not in result['execution_fault']['error']


def test_real_synthetic_batch_and_cache(tmp_path):
    workspace(tmp_path)
    first = run_family(tmp_path / 'family.json', tmp_path, workers=2)
    assert first['status'] == 'complete' and first['coverage']['successful'] == 2
    second = run_family(tmp_path / 'family.json', tmp_path, workers=1)
    assert second['coverage']['cache_hits'] == 2
