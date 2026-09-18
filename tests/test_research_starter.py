"""YAML model binding and a seeded, exhaustive research loop; no external models."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from n225m_bt.research import controller
from n225m_bt.research.agents import build_arguments, invoke_role
from n225m_bt.research.datasets import register_dataset, write_json
from n225m_bt.research.runner import read_spec
from n225m_bt.research.space import trials

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_model_environment(monkeypatch):
    monkeypatch.delenv("AS4FTS_DESIGN_MODEL", raising=False)
    monkeypatch.delenv("AS4FTS_IMPLEMENT_MODEL", raising=False)


def test_direct_model_and_prompt_are_literal(tmp_path):
    role = {"model": "model with space", "argv": ["agent", "--model", "{model}", "{prompt}", "{output}"]}
    prompt = "Do not replace literal {model} or {output} inside my text."
    assert build_arguments(role, prompt, tmp_path / "result.json") == [
        "agent", "--model", "model with space", prompt, str(tmp_path / "result.json")]


@pytest.mark.parametrize("model", [None, "", "   "])
@pytest.mark.parametrize("flag", ["--model", "-m"])
def test_default_model_omits_flag_and_value(model, flag, tmp_path):
    assert build_arguments({"model": model, "argv": ["agent", flag, "{model}", "-p"]}, "", tmp_path / "out") == ["agent", "-p"]


def test_equals_style_default_and_explicit_models(tmp_path):
    role = {"model": None, "argv": ["agent", "--model={model}"]}
    assert build_arguments(role, "", tmp_path / "out") == ["agent"]
    assert build_arguments(role | {"model": "yaml-choice"}, "", tmp_path / "out") == ["agent", "--model=yaml-choice"]


@pytest.mark.parametrize("token", ["${AS4FTS_DESIGN_MODEL}", "${AS4FTS_IMPLEMENT_MODEL}"])
def test_direct_model_supports_existing_local_argv(token, tmp_path):
    assert build_arguments({"model": "from-yaml", "argv": ["agent", "--model", token]}, "", tmp_path / "out")[-1] == "from-yaml"


def test_legacy_environment_still_works_when_no_direct_model(monkeypatch, tmp_path):
    monkeypatch.setenv("AS4FTS_DESIGN_MODEL", "legacy")
    role = {"argv": ["agent", "--model", "${AS4FTS_DESIGN_MODEL}"]}
    assert build_arguments(role, "", tmp_path / "out")[-1] == "legacy"


@pytest.mark.parametrize("model", [42, False, ["not-a-string"]])
def test_invalid_model_type_fails_with_actionable_error(model, tmp_path):
    with pytest.raises(ValueError, match="role.model"):
        build_arguments({"model": model, "argv": ["agent", "--model", "{model}"]}, "", tmp_path / "out")


def test_explicit_model_cannot_be_silently_ignored(tmp_path):
    with pytest.raises(ValueError, match="placeholder"):
        build_arguments({"model": "selected", "argv": ["agent"]}, "", tmp_path / "out")


def test_null_model_does_not_strip_unrelated_arguments(tmp_path):
    with pytest.raises(ValueError, match="null role.model"):
        build_arguments({"argv": ["agent", "--other", "{model}"]}, "", tmp_path / "out")


def test_yaml_model_is_recorded_and_changes_response_cache(tmp_path):
    import yaml
    agent = tmp_path / "agent.py"
    agent.write_text('import json,sys\nprint(json.dumps({"selected":sys.argv[1]}))\n', encoding="utf-8")
    config = tmp_path / "roles.yaml"
    config.write_text(yaml.safe_dump({"roles": {"designer": {
        "model": "first-model", "argv": [sys.executable, str(agent), "{model}"]}}}), encoding="utf-8")
    role = read_spec(config)["roles"]["designer"]
    folder = tmp_path / "call"
    assert invoke_role(role, "task", tmp_path, folder)["selected"] == "first-model"
    old = json.loads((folder / "response.json").read_text())
    assert old["requested_model"] == "first-model"
    assert invoke_role(role | {"model": "second-model"}, "task", tmp_path, folder)["selected"] == "second-model"
    assert json.loads((folder / "response.json").read_text())["request_id"] != old["request_id"]


def test_example_config_needs_no_environment_and_starter_has_16_cases(tmp_path):
    config = read_spec(ROOT / "config/research_agents.example.yaml")
    for role in config["roles"].values():
        command = build_arguments(role, "hello", tmp_path / "out")
        assert not any("${AS4FTS_" in token or "{model}" in token for token in command)
    spec = read_spec(ROOT / config["initial_family"])
    assert spec["implementation_required"] is False
    assert len(list(trials(spec))) == 16


def prepare_workspace(tmp_path):
    for name in ("src", "config", "prompts", "examples"):
        shutil.copytree(ROOT / name, tmp_path / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.local.yaml"))
    register_dataset(tmp_path, "campaign-input", synthetic_days=1)
    seed_path = tmp_path / "examples/research/starter_breakout.yaml"
    seed = read_spec(seed_path)
    seed["backtest"].pop("fees.jpy_per_side_per_contract")
    write_json(seed_path, seed)
    config = {"campaign_id": "seed-test", "dataset": "campaign-input", "max_families": 1,
              "initial_family": "examples/research/starter_breakout.yaml", "workers": 1,
              "defaults": {"backtest": {"fees.jpy_per_side_per_contract": 123}}, "roles": {}}
    path = tmp_path / "seed-loop.json"
    write_json(path, config)
    return path, seed_path


def test_seeded_family_needs_no_agent_and_resumes_without_seed_file(tmp_path):
    config, seed = prepare_workspace(tmp_path)
    state = controller.run_campaign(config, tmp_path)
    assert state["history"][0]["origin"] == "initial_family"
    summary = state["history"][0]["summary"]
    assert summary["coverage"]["successful"] == 16
    output = Path(summary["identity"]["output"])
    resolved = read_spec(output / "family.json")
    assert resolved["dataset"] == "campaign-input"
    assert resolved["backtest"]["fees.jpy_per_side_per_contract"] == 123
    seed.unlink()
    assert controller.run_campaign(config, tmp_path)["history"] == state["history"]


def test_seeded_timeout_resumes_same_saved_family(tmp_path, monkeypatch):
    config, seed = prepare_workspace(tmp_path)
    actual_run = controller.run_process

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("mock timeout", 0.1)

    monkeypatch.setattr(controller, "run_process", timeout)
    state = controller.run_campaign(config, tmp_path)
    assert state["status"] == "paused_timeout"
    assert state["active"]["stage"] == "backtest"
    seed.unlink()
    monkeypatch.setattr(controller, "run_process", actual_run)
    state = controller.run_campaign(config, tmp_path)
    assert state["history"][0]["summary"]["coverage"]["successful"] == 16


def test_full_offline_loop_script(tmp_path):
    for name in ("src", "config", "prompts", "examples"):
        shutil.copytree(ROOT / name, tmp_path / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.local.yaml"))
    result = subprocess.run([sys.executable, str(ROOT / "scripts/check_research_loop.py"), "--root", str(tmp_path)],
                            text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["ok"] and all(report["checks"].values())
    assert report["live_model_calls"] == 0
    assert [item["successful"] for item in report["coverage"]] == [16, 16]
