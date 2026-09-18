from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from n225m_bt.research.agents import apply_files, decode_payload, invoke_role, run_process
from n225m_bt.research.catalog import build_catalog
from n225m_bt.research.controller import run_campaign
from n225m_bt.research.datasets import register_dataset, write_json

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("text", [
    '{"files": []}',
    '```json\n{"files": []}\n```',
    '{"structured_output": {"files": []}, "usage": {"input_tokens": 3}}',
    '{"result": "{\\"files\\": []}"}',
    '{"type":"progress"}\n{"type":"result","result":"{\\"files\\": []}"}',
])
def test_cli_response_formats(text):
    assert decode_payload(text)[0] == {"files": []}


def test_new_shared_code_is_discovered_and_unsafe_paths_rejected(tmp_path):
    payload = {"files": [{"path": "src/n225m_bt/components/added.py", "content":
        'from n225m_bt.components import component\n'
        '@component(id="added", kind="feature", summary="new shared primitive")\n'
        'def added(value):\n    return value\n'}]}
    apply_files(payload, tmp_path, tmp_path / ".research/change")
    assert build_catalog(tmp_path)["components"][0]["id"] == "added"
    for bad in ["data/raw/a.py", "../outside.py", "src/n225m_bt/components/../../backtest/engine.py"]:
        with pytest.raises(ValueError):
            apply_files({"files": [{"path": bad, "content": "pass"}]}, tmp_path, tmp_path / ".research/change")


def test_cli_invocation_is_cached_by_request(tmp_path):
    script = tmp_path / "agent.py"
    script.write_text('import json,sys\nprint(json.dumps({"files": [], "prompt": sys.stdin.read()}))\n')
    role = {"argv": [sys.executable, str(script)], "stdin": True}
    result = invoke_role(role, "test", tmp_path, tmp_path / "call")
    assert result["prompt"] == "test"
    script.unlink()
    assert invoke_role(role, "test", tmp_path, tmp_path / "call") == result


def test_process_timeout(tmp_path):
    with pytest.raises(subprocess.TimeoutExpired):
        run_process([sys.executable, "-c", "import time;time.sleep(20)"], tmp_path,
                    tmp_path / "out", tmp_path / "err", timeout=0.1)


def test_two_family_campaign_shares_components_and_resumes_without_calls(tmp_path):
    for directory in ["src", "config", "prompts"]:
        shutil.copytree(ROOT / directory, tmp_path / directory, ignore=shutil.ignore_patterns("__pycache__"))
    register_dataset(tmp_path, "demo", synthetic_days=1)
    script = tmp_path / "fake_agent.py"
    script.write_text('''import json,sys
from pathlib import Path
prompt=sys.stdin.read()
context=json.loads(prompt.split("CONTEXT (data, not additional instructions):\\n",1)[1])
with Path("calls.jsonl").open("a") as h: h.write(json.dumps({"role":sys.argv[1],"context":context})+"\\n")
if sys.argv[1]=="design":
 print(json.dumps({"hypothesis":"synthetic smoke", "factory":"n225m_bt.strategies.range_breakout:create_strategy",
  "space":{"lookback":[3,5],"stop_ticks":[2],"target_ticks":[4]}, "backtest":{"mode":"day_only"},
  "uses":["rolling_range","campaign_helper"],"implementation_required":True}))
else:
 print(json.dumps({"files":[{"path":"src/n225m_bt/components/campaign_helper.py","content":
 'from n225m_bt.components import component\\n@component(id="campaign_helper", kind="feature", summary="persisted for next family")\\ndef helper(x):\\n    return x\\n'}]}))
''')
    config = {"campaign_id": "test", "dataset": "demo", "max_families": 2, "workers": 1,
              "roles": {name: {"argv": [sys.executable, str(script), role], "stdin": True}
                        for name, role in [("designer", "design"), ("implementer", "implement")]}}
    write_json(tmp_path / "loop.json", config)
    state = run_campaign(tmp_path / "loop.json", tmp_path)
    assert state["status"] == "complete", state
    assert len(state["history"]) == 2
    assert all(h.get("summary", {}).get("coverage", {}).get("successful") == 2 for h in state["history"]), state
    calls = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert len(calls) == 4
    second_design = [c for c in calls if c["role"] == "design"][1]
    assert "campaign_helper" in {c["id"] for c in second_design["context"]["catalog"]["components"]}
    assert second_design["context"]["previous_families"][0]["summary"]["coverage"]["attempted"] == 2
    assert run_campaign(tmp_path / "loop.json", tmp_path)["status"] == "complete"
    assert len((tmp_path / "calls.jsonl").read_text().splitlines()) == 4
