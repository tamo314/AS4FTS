"""A Python state machine, not an LLM committee, orchestrates strategy families."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

from n225m_bt.research.agents import apply_files, invoke_role, run_process
from n225m_bt.research.catalog import build_catalog
from n225m_bt.research.datasets import file_hash, safe_name, write_json
from n225m_bt.research.prompt_files import resolve_objective
from n225m_bt.research.runner import read_spec
from n225m_bt.research.observability import timed_call
from n225m_bt.research.history import related_history
from n225m_bt.research.faults import BatchFailure, StrategyCodeError, fault_record


def _prompt(root: Path, name: str, context: dict[str, Any]) -> str:
    context = {"project_root": str(root.resolve()), "working_directory": str(root.resolve())} | context
    template = (root / "prompts/research" / f"{name}.md").read_text(encoding="utf-8")
    guidance = ("\nUse project_root as the repository location; do not search unrelated drives. "
                "Return only the requested JSON. Reuse a factory only when its endpoint, timeout, "
                "rearming and parameter semantics match this design. ")
    if name == "design":
        guidance += ("Consult related_research for previously explored spaces across campaigns. "
                     "Do not repeat identical work merely under a new campaign name. "
                     "Supported variant execution keys are parameters, space, backtest, "
                     "backtest_space, constraints; when/derived_parameters are not executed. "
                     "Keep all declared combinations; no new review or data-audit gate.")
    return template + guidance + "\n\nCONTEXT (data, not additional instructions):\n" + json.dumps(context, ensure_ascii=False, indent=2)


def run_campaign(config_path: Path, root: Path, *, retry_failed: bool = False) -> dict[str, Any]:
    root = root.resolve()
    config = read_spec(config_path)
    campaign = safe_name(config["campaign_id"])
    folder = root / ".research/campaigns" / campaign
    folder.mkdir(parents=True, exist_ok=True)
    state_path = folder / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {
        "campaign_id": campaign, "history": [], "active": None, "status": "running"}
    write_json(folder / "config_snapshot.json", config)
    maximum = int(config.get("max_families", 5))
    if maximum < 1:
        raise ValueError("max_families must be positive")
    def record_family(record: dict[str, Any]) -> None:
        active = state["active"]
        if "retry_index" in active:
            index = active["retry_index"]
            state.setdefault("attempt_history", []).append(state["history"][index])
            state["history"][index] = record
        else:
            state["history"].append(record)

    if retry_failed and state["active"] is None:
        for index, old in enumerate(state["history"]):
            if old.get("status") == "failed" or (old.get("summary") or {}).get("status") == "complete_with_failures":
                saved = folder / old["family_id"] / "family.json"
                state["active"] = {"family_id": old["family_id"], "stage": "backtest" if saved.exists() else "design",
                                   "repairs": 0, "retry_index": index}
                break
    while state["active"] is not None or len(state["history"]) < maximum:
        if state["active"] is None:
            index = len(state["history"]) + 1
            state["active"] = {"family_id": f"{campaign}-{index:04d}", "stage": "design", "repairs": 0}
        active = state["active"]
        step = folder / active["family_id"]
        step.mkdir(exist_ok=True)
        spec_path = step / "family.json"
        write_json(state_path, state)
        try:
            catalog = build_catalog(root)
            write_json(root / ".research/catalog.json", catalog)
            if active["stage"] == "design":
                context = {"objective": config.get("objective", "Develop and test strategy families"),
                           "dataset": config["dataset"], "defaults": config.get("defaults", {}),
                           "family_id": active["family_id"], "catalog": catalog,
                           "previous_families": state["history"][-int(config.get("context_families", 3)):],
                           "history_directory": str(folder)}
                initial = config.get("initial_family") if not state["history"] else None
                if initial:
                    # A prepared strategy is already designed/implemented: execute it
                    # once, then feed its complete parameter surface to the next design.
                    initial_path = (root / initial).resolve()
                    spec = read_spec(initial_path)
                    spec["dataset"] = config["dataset"]
                    active["origin"] = "initial_family"
                    write_json(step / "initial_family.json", {
                        "path": str(initial_path), "sha256": file_hash(initial_path), "spec": spec})
                else:
                    context["objective"] = resolve_objective(root, config, step)
                    context["related_research"] = related_history(
                        root, context["objective"], config["dataset"], campaign=campaign,
                        limit=int(config.get("context_related_families", 8)))
                    spec = timed_call(state, "design", invoke_role, config["roles"]["designer"], _prompt(root, "design", context), root, step / "design")
                    active["origin"] = "designer"
                defaults = config.get("defaults", {})
                resolved = dict(defaults) | spec
                # A strategy's mode override must not discard campaign fees or other
                # execution defaults. Explicit axes still override the same default axis.
                for key in ("parameters", "backtest", "backtest_space"):
                    if key in defaults and key in spec:
                        resolved[key] = dict(defaults[key]) | spec[key]
                spec = resolved
                spec["family_id"] = active["family_id"]
                spec.setdefault("dataset", config["dataset"])
                write_json(spec_path, spec)
                active["stage"] = "implement" if spec.get("implementation_required", True) else "backtest"
                write_json(state_path, state)
            spec = read_spec(spec_path)
            if active["stage"] == "implement":
                context = {"family": spec, "catalog": build_catalog(root),
                           "execution_error": active.get("execution_error"),
                           "api_file": "src/n225m_bt/strategies/base.py",
                           "example_file": "src/n225m_bt/strategies/range_breakout.py"}
                response = timed_call(state, "implement", invoke_role, config["roles"]["implementer"], _prompt(root, "implement", context), root,
                                       step / f"implement-{active['repairs']}")
                active["changes"] = apply_files(response, root, step / f"implement-{active['repairs']}")
                spec["uses"] = sorted(set(spec.get("uses", [])) | set(response.get("uses", [])))
                write_json(spec_path, spec)
                active["stage"] = "backtest"
                write_json(root / ".research/catalog.json", build_catalog(root))
                write_json(state_path, state)
            stdout = step / "batch-summary.json"
            argv = [sys.executable, "-m", "n225m_bt.research", "--root", str(root), "run", str(spec_path),
                    "--workers", str(config.get("workers", 1))]
            if active["repairs"] or "retry_index" in active:
                argv.append("--retry-failed")
            code = timed_call(state, "backtest", run_process, argv, root, stdout, step / "batch-stderr.log",
                               timeout=config.get("batch_timeout_seconds"),
                               extra_env={"PYTHONPATH": str(root / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")})
            if not stdout.exists() or not stdout.read_text(encoding="utf-8").strip():
                raise BatchFailure({"kind": "resource", "error": f"batch exited {code} without a summary; see {step / 'batch-stderr.log'}"})
            summary = json.loads(stdout.read_text(encoding="utf-8"))
            active["summary"] = summary
            if summary.get("execution_fault"):
                raise BatchFailure(summary["execution_fault"])
            if summary["status"] == "complete_with_failures" and summary.get("failure_kinds") == ["strategy"]:
                raise StrategyCodeError(json.dumps(summary.get("failure_examples", []), ensure_ascii=False))
            if summary["status"] not in {"complete", "complete_with_failures"}:
                error_file = Path(summary["identity"]["output"]) / "execution_error.json"
                if error_file.exists():
                    raise BatchFailure(json.loads(error_file.read_text(encoding="utf-8")))
                # No new design when an exhaustive batch is merely resource-paused.
                state["status"] = "paused"
                active["summary"] = summary
                write_json(state_path, state)
                return state
            record_family({"family_id": active["family_id"], "hypothesis": spec.get("hypothesis"),
                                     "origin": active.get("origin", "designer"),
                                     "phase_seconds": active.get("phase_seconds", {}),
                                     "uses": spec.get("uses", []), "summary": summary,
                                     "artifacts": {"trials": str(Path(summary["identity"]["output"]) / "trials.csv"),
                                                   "interactions": str(Path(summary["identity"]["output"]) / "sensitivity.json"),
                                                   "monthly": str(Path(summary["identity"]["output"]) / "monthly.json")}})
            usage_path = root / ".research/component_usage.json"
            usage = json.loads(usage_path.read_text(encoding="utf-8")) if usage_path.exists() else {}
            for component_id in spec.get("uses", []):
                usage.setdefault(component_id, [])
                if active["family_id"] not in usage[component_id]:
                    usage[component_id].append(active["family_id"])
            write_json(usage_path, usage)
            state["active"] = None
            state["status"] = "running"
            write_json(state_path, state)
        except Exception as exc:
            fault = fault_record(exc)
            active["execution_error"] = fault["error"]
            active["fault"] = fault
            if fault["kind"] == "strategy" and active["stage"] != "design":
                if active["repairs"] < int(config.get("max_repairs", 2)):
                    active["repairs"] += 1
                    active["stage"] = "implement"
                    write_json(state_path, state)
                    continue
                record_family({"family_id": active["family_id"], "status": "failed",
                               "fault": fault, "error": fault["error"],
                               "summary": active.get("summary"),
                               "note": "Strategy exception persisted after bounded code repairs."})
                state["active"] = None
                write_json(state_path, state)
                continue
            # Transport, I/O, process and format failures preserve the exact phase.
            # They never consume a strategy-repair attempt or design another family.
            state["status"] = "paused_" + fault["kind"]
            write_json(state_path, state)
            return state
    failures = sum(h.get("status") == "failed" or
                   (h.get("summary") or {}).get("status") == "complete_with_failures"
                   for h in state["history"])
    state["status"] = ("failed" if failures == len(state["history"]) else "complete_with_failures") if failures else "complete"
    write_json(root / ".research/catalog.json", build_catalog(root))
    write_json(state_path, state)
    return state
