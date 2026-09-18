"""Offline two-family wiring check: real backtests, synthetic bars, mock CLI roles.

Run from the repository with: python scripts/check_research_loop.py
This does not invoke Codex/Claude/Antigravity, read market data, or edit shared source.
All generated code and results stay in a new .research/smoke/ workspace.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from n225m_bt.research.catalog import build_catalog
from n225m_bt.research.controller import run_campaign
from n225m_bt.research.datasets import register_dataset, write_json
from n225m_bt.research.runner import read_spec


def mock_role(role: str, model: str) -> None:
    """CLI protocol fixture, not a strategy-generating model."""
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    context = json.loads(sys.stdin.read().split(
        "CONTEXT (data, not additional instructions):\n", 1)[1])
    with Path("mock_calls.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"role": role, "model": model, "context": context}) + "\n")
    if role == "design":
        spec = read_spec(Path("examples/research/starter_breakout.yaml"))
        spec.update({
            "hypothesis": "MOCK protocol check: reuse the seeded strategy through a new shared factory",
            "factory": "n225m_bt.strategies.smoke_followup:create_strategy",
            "implementation_required": True,
            "uses": ["rolling_range", "tick_bracket", "smoke_followup"],
        })
        print(json.dumps(spec))
    else:
        # Exercise code application/catalog refresh without duplicating trading logic.
        content = (
            'from n225m_bt.components import component\n'
            'from n225m_bt.strategies.range_breakout import create_strategy as existing_factory\n\n'
            '@component(id="smoke_followup", kind="strategy", summary="Mock-loop reusable adapter", '
            'uses=["rolling_range", "tick_bracket"])\n'
            'def create_strategy(parameters):\n'
            '    """Reuse the shared implementation; return fresh state for each case."""\n'
            '    return existing_factory(parameters)\n'
        )
        print(json.dumps({"files": [{
            "path": "src/n225m_bt/strategies/smoke_followup.py", "content": content}]}))


def run_check(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    destination = root / ".research/smoke"
    destination.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="starter-", dir=destination))
    shutil.copytree(root / "src", workspace / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(root / "prompts/research", workspace / "prompts/research")
    (workspace / "config").mkdir()
    for name in ("instrument.yaml", "sessions.yaml", "backtest.yaml"):
        shutil.copy2(root / "config" / name, workspace / "config" / name)
    (workspace / "examples/research").mkdir(parents=True)
    shutil.copy2(root / "examples/research/starter_breakout.yaml", workspace / "examples/research/starter_breakout.yaml")
    register_dataset(workspace, "demo", synthetic_days=3)
    config = {
        "campaign_id": "starter_smoke", "dataset": "demo", "max_families": 2,
        "initial_family": "examples/research/starter_breakout.yaml", "workers": 2,
        "max_repairs": 0, "batch_timeout_seconds": 60,
        "roles": {name: {
            "model": f"mock-{name}-from-yaml",
            "argv": [sys.executable, str(Path(__file__).resolve()), "--mock-role", role, "--model", "{model}"],
            "stdin": True, "timeout_seconds": 30,
        } for name, role in (("designer", "design"), ("implementer", "implement"))},
    }
    # YAML is deliberately used here: no model environment variable is required.
    import yaml
    config_path = workspace / "config/loop.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    state = run_campaign(config_path, workspace)
    history = state["history"]
    calls_path = workspace / "mock_calls.jsonl"
    calls = [json.loads(line) for line in calls_path.read_text(encoding="utf-8").splitlines()] if calls_path.exists() else []
    coverage = [family.get("summary", {}).get("coverage", {}) for family in history]
    checks = {
        "two_complete_families": state["status"] == "complete" and len(history) == 2
            and all(family.get("summary", {}).get("status") == "complete" for family in history),
        "all_16_cases_per_family": len(coverage) == 2 and all(
            item.get("planned") == item.get("attempted") == item.get("successful") == 16
            and item.get("failed") == item.get("remaining") == 0 for item in coverage),
        "prepared_first_family_reused": bool(history) and history[0].get("origin") == "initial_family",
        "one_design_one_implementation": [call["role"] for call in calls] == ["design", "implement"],
        "models_from_yaml": [call["model"] for call in calls] == ["mock-designer-from-yaml", "mock-implementer-from-yaml"],
        "previous_results_reach_design": bool(calls) and bool(calls[0]["context"].get("previous_families"))
            and calls[0]["context"]["previous_families"][0]["summary"]["coverage"]["successful"] == 16,
        "shared_factory_discovered": "smoke_followup" in {
            component["id"] for component in build_catalog(workspace)["components"]},
    }
    call_count = len(calls)
    if checks["two_complete_families"]:
        run_campaign(config_path, workspace)
        checks["completed_resume_has_no_new_calls"] = len(calls_path.read_text(encoding="utf-8").splitlines()) == call_count
    else:
        checks["completed_resume_has_no_new_calls"] = False
    report = {"ok": all(checks.values()), "checks": checks, "coverage": coverage,
              "workspace": str(workspace), "agents": "mock_cli", "data": "synthetic",
              "backtest": "actual_engine", "live_model_calls": 0}
    write_json(workspace / "check_result.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--mock-role", choices=("design", "implement"), help=argparse.SUPPRESS)
    parser.add_argument("--model", default="mock", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.mock_role:
        mock_role(args.mock_role, args.model)
        return 0
    report = run_check(args.root)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
