from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest
import yaml

from n225m_bt.research.prompt_files import resolve_objective

ROOT = Path(__file__).parents[1]
INDEX = json.loads((ROOT / "prompts/research/hypotheses/index.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("item", INDEX, ids=lambda item: item["id"])
def test_prompt_contains_complete_declared_grid(item):
    text = (ROOT / item["objective_file"]).read_text(encoding="utf-8")
    spec = yaml.safe_load(text.split("```yaml\n", 1)[1].split("```", 1)[0])
    axes = list(spec["space"].values()) + list(spec["backtest_space"].values())
    assert len(list(itertools.product(*axes))) == item["planned_trials"]
    assert all(len(axis) == len(set(axis)) for axis in axes)
    assert spec["backtest"]["mode"] == item["mode"]
    assert spec["space"]["direction"] == ["long", "short"]
    assert spec["backtest_space"]["execution.slippage_ticks"] == [0, 1, 2]
    assert spec["implementation_required"] is True
    assert "factory" in spec and "design" in text


def test_total_and_h05_observation_mode():
    assert sum(item["planned_trials"] for item in INDEX) == 2160
    assert [item["id"] for item in INDEX if item["mode"] == "full_session"] == ["H05"]


def test_objective_file_is_root_relative_and_snapshotted(tmp_path):
    path = tmp_path / "hypotheses/h01.md"
    path.parent.mkdir()
    path.write_text("\ufeff日本語の仮説", encoding="utf-8")
    config = {"objective": "共通目的", "objective_file": "hypotheses/h01.md"}
    step = tmp_path / ".research/family1"
    result = resolve_objective(tmp_path, config, step)
    assert result == "共通目的\n\n日本語の仮説"
    saved = json.loads((step / "objective_snapshot.json").read_text(encoding="utf-8"))
    assert saved["path"] == str(path.resolve())
    assert len(saved["sha256"]) == 64
    path.write_text("後で編集", encoding="utf-8")
    assert resolve_objective(tmp_path, config, step) == result
    assert "後で編集" in resolve_objective(tmp_path, config, tmp_path / ".research/newfamily")


def test_existing_string_objective_unchanged(tmp_path):
    assert resolve_objective(tmp_path, {"objective": "old"}, tmp_path) == "old"
    assert not (tmp_path / "objective_snapshot.json").exists()


@pytest.mark.parametrize("value", ["", "  \n"])
def test_empty_prompt_is_input_error(tmp_path, value):
    (tmp_path / "empty.md").write_text(value)
    with pytest.raises(ValueError, match="empty"):
        resolve_objective(tmp_path, {"objective_file": "empty.md"}, tmp_path / "out")


def test_missing_file_is_input_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        resolve_objective(tmp_path, {"objective_file": "not_found.md"}, tmp_path / "out")


def test_agy_template_has_stream_stdin_and_no_initial_bypass():
    config = yaml.safe_load((ROOT / "config/research_agents.agy.example.yaml").read_text(encoding="utf-8"))
    role = config["roles"]["implementer"]
    assert config["initial_family"] is None
    assert (ROOT / config["objective_file"]).exists()
    assert role["stdin"] is True and role["stdin_format"] == "agy_stream_json"
    assert role["argv"].count("stream-json") == 2
    assert "-p" not in role["argv"] and "{prompt}" not in role["argv"]
    schema = ROOT / role["argv"][role["argv"].index("--json-schema") + 1]
    assert json.loads(schema.read_text())["required"] == ["files"]
