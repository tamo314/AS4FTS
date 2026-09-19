"""Run with python -m n225m_bt.research; no separate service or UI required."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from n225m_bt.research.catalog import build_catalog
from n225m_bt.research.datasets import register_dataset, write_json
from n225m_bt.research.runner import read_spec, run_family
from n225m_bt.research.space import trials


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Strategy-family batch research")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    commands = parser.add_subparsers(dest="command", required=True)
    register = commands.add_parser("dataset-register", help="Register existing Gold once; no re-ingest")
    register.add_argument("name")
    register.add_argument("--gold-root", type=Path)
    register.add_argument("--calendar", type=Path)
    register.add_argument("--synthetic-days", type=int, default=0)
    commands.add_parser("catalog", help="Discover reusable code and write .research/catalog.json")
    history = commands.add_parser("history", help="Inspect cross-campaign research summaries, without data reads")
    history.add_argument("--query", default="")
    history.add_argument("--dataset", default="")
    history.add_argument("--limit", type=int, default=8)
    plan = commands.add_parser("plan", help="Show the complete finite space size; not an approval")
    plan.add_argument("spec", type=Path)
    run = commands.add_parser("run", help="Execute all cases, or resume identical inputs")
    run.add_argument("spec", type=Path)
    run.add_argument("--workers", type=int, default=1)
    run.add_argument("--max-new-trials", type=int, help="Pause after N new cases; never sample")
    run.add_argument("--retry-failed", action="store_true")
    loop = commands.add_parser("loop", help="Design -> one implementation -> whole batch -> next family")
    loop.add_argument("--config", type=Path, required=True)
    loop.add_argument("--retry-failed", action="store_true", help="Retry earliest recorded failed family using its saved specification")
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    if arguments.command == "dataset-register":
        print(register_dataset(root, arguments.name, arguments.gold_root,
                               calendar=arguments.calendar, synthetic_days=arguments.synthetic_days))
    elif arguments.command == "catalog":
        catalog = build_catalog(root)
        write_json(root / ".research/catalog.json", catalog)
        print(json.dumps(catalog, ensure_ascii=False, indent=2))
    elif arguments.command == "history":
        from n225m_bt.research.history import related_history
        print(json.dumps(related_history(root, arguments.query, arguments.dataset,
                                        limit=arguments.limit), ensure_ascii=False, indent=2))
    elif arguments.command == "plan":
        spec = read_spec(arguments.spec)
        combinations = sum(1 for _ in trials(spec))
        print(json.dumps({"strategy_combinations": combinations,
                          "periods": len(spec.get("periods", {"explore": {}})),
                          "planned_trials": combinations * len(spec.get("periods", {"explore": {}}))}))
    elif arguments.command == "run":
        summary = run_family(arguments.spec, root, workers=arguments.workers,
                             max_new_trials=arguments.max_new_trials, retry_failed=arguments.retry_failed)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["status"] in {"complete", "complete_with_failures"} else 2
    elif arguments.command == "loop":
        from n225m_bt.research.controller import run_campaign
        state = run_campaign(arguments.config, root, retry_failed=arguments.retry_failed)
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0 if state["status"] == "complete" else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
