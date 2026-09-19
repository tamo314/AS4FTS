import json
import sys

from n225m_bt.research import controller
from n225m_bt.research.datasets import write_json
from test_research_fault_routing import workspace


def test_cross_campaign_memory_and_cache_in_real_loop(tmp_path):
    config = workspace(tmp_path)
    first = controller.run_campaign(tmp_path / 'loop.json', tmp_path)
    assert first['status'] == 'complete'
    script = tmp_path / 'designer.py'
    script.write_text('''import json,sys
from pathlib import Path
prompt=sys.stdin.read()
ctx=json.loads(prompt.split("CONTEXT (data, not additional instructions):\\n",1)[1])
Path("received_context.json").write_text(json.dumps(ctx))
print(json.dumps({"factory":"n225m_bt.strategies.range_breakout:create_strategy",
"implementation_required":False,"space":{"lookback":[3,5],"stop_ticks":[2],"target_ticks":[4]},
"backtest":{"mode":"day_only"},"hypothesis":"reuse existing research"}))
''')
    config.update(campaign_id='second', initial_family=None)
    config['roles']['designer'] = {'argv': [sys.executable, str(script)], 'stdin': True}
    write_json(tmp_path / 'second.json', config)
    second = controller.run_campaign(tmp_path / 'second.json', tmp_path)
    assert second['status'] == 'complete', second
    assert second['history'][0]['summary']['coverage']['cache_hits'] == 2
    context = json.loads((tmp_path / 'received_context.json').read_text())
    assert context['related_research']['records']
    assert context['related_research']['records'][0]['tested_space']['space']['lookback'] == [3, 5]
    assert context['project_root'] == str(tmp_path)
    assert second['phase_seconds']['design'] > 0


def test_recorded_failure_retry_preserves_attempt_and_spec(tmp_path, monkeypatch):
    workspace(tmp_path)
    fail = [True]
    seen = []
    def result(argv, root, stdout, stderr, **kw):
        seen.append(argv)
        if fail[0]:
            summary = {'status': 'complete_with_failures', 'failure_kinds': ['strategy'],
                'failure_examples': [{'error': 'broken strategy'}],
                'identity': {'output': str(tmp_path / 'batch')}, 'coverage': {'failed': 2}}
        else:
            summary = {'status': 'complete', 'identity': {'output': str(tmp_path / 'batch')},
                       'coverage': {'successful': 2, 'failed': 0, 'remaining': 0}}
        write_json(stdout, summary)
        return 0
    monkeypatch.setattr(controller, 'run_process', result)
    monkeypatch.setattr(controller, 'invoke_role', lambda *a, **k: (_ for _ in ()).throw(AssertionError('unexpected AI')))
    assert controller.run_campaign(tmp_path / 'loop.json', tmp_path)['status'] == 'failed'
    fail[0] = False
    fixed = controller.run_campaign(tmp_path / 'loop.json', tmp_path, retry_failed=True)
    assert fixed['status'] == 'complete'
    assert len(fixed['history']) == 1 and len(fixed['attempt_history']) == 1
    assert '--retry-failed' in seen[-1]
