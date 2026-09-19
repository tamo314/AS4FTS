"""Implement once, execute every declared combination, persist and resume by identity."""
from __future__ import annotations

import gzip
import importlib
import importlib.metadata
import json
import multiprocessing
import random
import sqlite3
import sys
import time
import traceback
import zipfile
import uuid
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

import yaml

from n225m_bt.backtest.engine import BacktestEngine
from n225m_bt.calendar.classifier import CalendarClassifier
from n225m_bt.calendar.model import ExchangeCalendar
from n225m_bt.config import BacktestConfig, InstrumentConfig, SessionsConfig, load_yaml_model
from n225m_bt.research.catalog import build_catalog
from n225m_bt.research.datasets import file_hash, load_bars, load_descriptor, safe_name, write_json
from n225m_bt.research.reporting import trade_metrics, write_report
from n225m_bt.research.space import canonical, digest, trials
from n225m_bt.research.observability import strategy_diagnostics
from n225m_bt.research.dependencies import dependency_manifest
from n225m_bt.research.faults import BatchFailure, StrategyCodeError, fault_record

_CONTEXT: dict[str, Any] = {}


def read_spec(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("family specification must be a JSON/YAML mapping")
    return cast(dict[str, Any], json.loads(json.dumps(payload, default=str)))


def code_manifest(root: Path) -> dict[str, str]:
    # Conservative invalidation includes newly added shared modules. No raw data scan.
    return {p.relative_to(root).as_posix(): file_hash(p)
            for p in sorted((root / "src/n225m_bt").rglob("*.py"))}


def environment_id() -> dict[str, str]:
    versions = {"python": sys.version.split()[0]}
    for package in importlib.metadata.distributions():
        name = package.metadata.get("Name")
        if name:
            versions[name] = package.version
    return versions


def _config_payload(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    folder = root / spec.get("config_dir", "config")
    return {"instrument": load_yaml_model(folder / "instrument.yaml", InstrumentConfig).model_dump(mode="json"),
            "sessions": load_yaml_model(folder / "sessions.yaml", SessionsConfig).model_dump(mode="json"),
            "backtest": load_yaml_model(folder / "backtest.yaml", BacktestConfig).model_dump(mode="json")}


def _overrides(base: dict[str, Any], changes: dict[str, Any]) -> BacktestConfig:
    payload = json.loads(canonical(base))
    for key, value in changes.items():
        parts = key.split(".")
        node = payload
        for part in parts[:-1]:
            if part not in node or not isinstance(node[part], dict):
                raise ValueError(f"unknown backtest path: {key}")
            node = node[part]
        if parts[-1] not in node:
            raise ValueError(f"unknown backtest field: {key}")
        node[parts[-1]] = value
    return BacktestConfig.model_validate(payload)


def _setup(root_text: str, descriptor: dict[str, Any], periods: dict[str, Any],
           config: dict[str, Any], factory_name: str, calendar_text: str | None,
           seed: int, cache_text: str) -> None:
    root = Path(root_text)
    sys.path.insert(0, str(root / "src"))
    importlib.invalidate_caches()
    # Each family has a fresh strategy/module import. Workers never share strategy instances.
    for name in list(sys.modules):
        if name.startswith(("n225m_bt.strategies.", "n225m_bt.components.")) and name != "n225m_bt.strategies.base":
            del sys.modules[name]
    try:
        module, separator, symbol = factory_name.partition(":")
        if not separator or not module.startswith("n225m_bt."):
            raise ValueError("factory must be a shared n225m_bt.module:create_strategy symbol")
        factory = getattr(importlib.import_module(module), symbol)
        if not callable(factory):
            raise ValueError("strategy factory is not callable")
    except Exception as exc:
        raise StrategyCodeError(f"cannot load strategy factory {factory_name}: {exc}") from exc
    starts = [p.get("start") for p in periods.values()]
    ends = [p.get("end") for p in periods.values()]
    first = min(starts) if starts and all(starts) else None
    last = max(ends) if ends and all(ends) else None
    all_bars = load_bars(descriptor, first, last)
    bars_by_period = {}
    for name, period in periods.items():
        start, end = period.get("start"), period.get("end")
        if start and end and start > end:
            raise ValueError(f"invalid period: {name}")
        bars_by_period[name] = [b for b in all_bars if
            (not start or b.trade_date.isoformat() >= start) and
            (not end or b.trade_date.isoformat() <= end)]
        if not bars_by_period[name]:
            raise ValueError(f"no bars for period {name}")
    calendar = ExchangeCalendar.from_path(Path(calendar_text)) if calendar_text else None
    _CONTEXT.clear()
    _CONTEXT.update(factory=factory, bars=bars_by_period, config=config,
                    classifier=CalendarClassifier(SessionsConfig.model_validate(config["sessions"]), calendar),
                    instrument=InstrumentConfig.model_validate(config["instrument"]).instrument.to_spec(),
                    seed=seed, cache=Path(cache_text), configs={})


def _setup_safe(*args: Any) -> None:
    # Initializer exceptions otherwise lose their cause behind BrokenProcessPool.
    try:
        _setup(*args)
    except Exception as exc:
        _CONTEXT.clear()
        _CONTEXT["setup_error"] = fault_record(exc)


def _run_case(case: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    row = dict(case) | {"cache_hit": False, "status": "failed", "error": None}
    try:
        if "setup_error" in _CONTEXT:
            raise BatchFailure(_CONTEXT["setup_error"])
        random.seed(_CONTEXT["seed"])
        configuration_key = digest(case["backtest"])
        if configuration_key not in _CONTEXT["configs"]:
            _CONTEXT["configs"][configuration_key] = _overrides(_CONTEXT["config"]["backtest"], case["backtest"])
        strategy = _CONTEXT["factory"](dict(case["parameters"]))
        bars = _CONTEXT["bars"][case["period"]]
        engine_started = time.perf_counter()
        result = BacktestEngine(_CONTEXT["instrument"], _CONTEXT["configs"][configuration_key],
                                _CONTEXT["classifier"]).run(bars, strategy, case["trial_id"], assume_sorted=True)
        row["engine_seconds"] = time.perf_counter() - engine_started
        row["diagnostics"] = strategy_diagnostics(strategy)
        row["metrics"] = trade_metrics(result.trades) | {
            "canceled_orders": result.canceled_orders, "bar_count": len(bars),
            "eligible_bar_count": result.eligible_bars,
            "entry_signals_returned": result.entry_signals_returned,
            "exit_signals_returned": result.exit_signals_returned}
        if result.equity and result.equity[-1] != row["metrics"]["net_pnl_jpy"]:
            raise ValueError("trade ledger and final realized equity disagree")
        folder = _CONTEXT["cache"] / case["trial_id"]
        folder.mkdir(parents=True, exist_ok=True)
        temp = folder / "trades.jsonl.gz.tmp"
        with gzip.open(temp, "wt", encoding="utf-8") as handle:
            for trade in result.trades:
                handle.write(json.dumps(asdict(trade), default=str, sort_keys=True) + "\n")
        temp.replace(folder / "trades.jsonl.gz")
        row["trades_path"] = str(folder / "trades.jsonl.gz")
        row["status"] = "ok"
    except Exception as exc:
        fault = fault_record(exc, default="strategy")
        row["error"] = fault["error"]
        row["error_kind"] = fault["kind"]
    row["elapsed_seconds"] = time.perf_counter() - started
    return row


def run_family(spec_path: Path, root: Path, *, workers: int = 1,
               max_new_trials: int | None = None, retry_failed: bool = False) -> dict[str, Any]:
    """Resource limits pause, never sample. Reinvoke the same spec to resume.

    All imports are trusted local Python. This function is not an OS sandbox.
    A fresh process per worker loads bars once, then creates one strategy per case.
    """
    invocation_started = time.perf_counter()
    root = root.resolve()
    spec = read_spec(spec_path)
    safe_name(spec["family_id"])
    if workers < 1 or (max_new_trials is not None and max_new_trials < 0):
        raise ValueError("workers must be positive and max_new_trials nonnegative")
    descriptor = load_descriptor(root, spec["dataset"])
    config = _config_payload(root, spec)
    sources = code_manifest(root)
    dependencies = dependency_manifest(root, spec["factory"], spec)
    periods = spec.get("periods", {"explore": {"start": spec.get("start"), "end": spec.get("end")}})
    if not periods:
        raise ValueError("at least one period is required")
    runtime = {"code": dependencies["code"], "resources": dependencies["resources"],
               "cache_identity_version": dependencies["identity_version"], "environment": environment_id(), "config": config,
               "dataset_id": descriptor["dataset_id"], "factory": spec["factory"],
               "seed": spec.get("seed", 0)}
    if not dependencies["cacheable"]:
        runtime["uncertain_dependency_nonce"] = uuid.uuid4().hex
    cases = []
    for point in trials(spec):
        for name, bounds in periods.items():
            case = point | {"period": name}
            case["trial_id"] = digest({"runtime": runtime, "point": point, "period": {"name": name, "bounds": bounds}})
            cases.append(case)
    if not cases:
        raise ValueError("the declared constraints leave no parameter combinations")
    # Include names as well as bounds in the batch identity; result keys use bounds.
    batch_id = digest({"runtime": runtime, "spec": spec})
    output = root / ".research/batches" / spec["family_id"] / batch_id
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "family.json", spec)
    write_json(output / "runtime.json", runtime)
    write_json(output / "dependencies.json", dependencies)
    write_json(output / "dataset.json", descriptor)
    catalog = build_catalog(root)
    write_json(output / "catalog.json", catalog)
    inferred = sorted({entry["id"] for entry in catalog["components"]
                       if entry.get("path") in dependencies["code"] and entry.get("id")})
    write_json(output / "component_usage.json", {
        "declared": spec.get("uses", []), "referenced_modules_components": inferred,
        "note": "Module references are static evidence, not a per-function invocation trace."})
    references_path = root / ".research/component_references.json"
    references = json.loads(references_path.read_text(encoding="utf-8")) if references_path.exists() else {}
    for component_id in inferred:
        references.setdefault(component_id, [])
        if spec["family_id"] not in references[component_id]:
            references[component_id].append(spec["family_id"])
    write_json(references_path, references)
    if not (output / "source.zip").exists():
        with zipfile.ZipFile(output / "source.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sources:
                archive.write(root / path, path)
    calendar_path = None
    if "calendar" in descriptor:
        calendar_path = output / ("calendar" + descriptor["calendar"]["suffix"])
        calendar_path.write_text(descriptor["calendar"]["content"], encoding="utf-8")
    cache = root / ".research/cache"
    cache.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(root / ".research/results.sqlite3", timeout=30)
    database.execute("PRAGMA journal_mode=WAL")
    database.executescript("""
        CREATE TABLE IF NOT EXISTS results (trial_id TEXT PRIMARY KEY, result TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS batch_trials (batch_id TEXT, trial_id TEXT, result TEXT NOT NULL,
                                                 PRIMARY KEY(batch_id, trial_id));
        CREATE TABLE IF NOT EXISTS attempts (batch_id TEXT, trial_id TEXT, result TEXT NOT NULL);
    """)
    rows: dict[str, dict[str, Any]] = {}
    pending = []
    for case in cases:
        previous = database.execute("SELECT result FROM batch_trials WHERE batch_id=? AND trial_id=?",
                                    (batch_id, case["trial_id"])).fetchone()
        cached = database.execute("SELECT result FROM results WHERE trial_id=?", (case["trial_id"],)).fetchone()
        record = json.loads((previous or cached)[0]) if (previous or cached) else None
        if record and record["status"] == "ok" and Path(record["trades_path"]).exists():
            rows[case["trial_id"]] = record | case | {"cache_hit": True}
        elif record and previous and record["status"] == "failed" and record.get("error_kind", "strategy") == "strategy" and not retry_failed:
            rows[case["trial_id"]] = record | case
        else:
            pending.append(case)
    selected = pending if max_new_trials is None else pending[:max_new_trials]
    identity = {"family_id": spec["family_id"], "batch_id": batch_id,
                "dataset_id": descriptor["dataset_id"], "output": str(output),
                "source_id": digest(dependencies), "hypothesis": spec.get("hypothesis", "")}

    def save(row: dict[str, Any]) -> None:
        key, encoded = row["trial_id"], canonical(row)
        rows[key] = row
        database.execute("INSERT OR REPLACE INTO batch_trials VALUES (?,?,?)", (batch_id, key, encoded))
        database.execute("INSERT INTO attempts VALUES (?,?,?)", (batch_id, key, encoded))
        if row["status"] == "ok":
            database.execute("INSERT OR REPLACE INTO results VALUES (?,?)", (key, encoded))
        database.commit()
        # Constant-cost checkpoint per trial; full reports are written once per invocation.
        write_json(output / "progress.json", {"planned": len(cases), "attempted": len(rows),
                                             "remaining": len(cases) - len(rows)})

    execution_fault = None
    (output / "execution_error.json").unlink(missing_ok=True)
    try:
        if selected:
            arguments = (str(root), descriptor, periods, config, spec["factory"],
                         str(calendar_path) if calendar_path else None,
                         int(spec.get("seed", 0)), str(cache))
            with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn"),
                                     initializer=_setup_safe, initargs=arguments) as executor:
                # Bound the queue and checkpoint in completion order, avoiding head-of-line blocking.
                iterator = iter(selected)
                futures = set()
                for _ in range(min(len(selected), workers * 2)):
                    futures.add(executor.submit(_run_case, next(iterator)))
                while futures:
                    done, futures = wait(futures, return_when=FIRST_COMPLETED)
                    for future in done:
                        row = future.result()
                        save(row)
                        if row.get("error_kind") not in {None, "strategy"}:
                            for outstanding in futures:
                                outstanding.cancel()
                            raise BatchFailure({"kind": row["error_kind"], "error": row["error"]})
                        case = next(iterator, None)
                        if case is not None:
                            futures.add(executor.submit(_run_case, case))
    except Exception as exc:
        execution_fault = fault_record(exc)
        write_json(output / "execution_error.json", execution_fault)
    finally:
        database.close()
    ordered_rows = [rows[c["trial_id"]] | {"period": c["period"]} for c in cases if c["trial_id"] in rows]
    summary = write_report(output, ordered_rows, len(cases), identity)
    summary["timing"] = {"invocation_wall_seconds": time.perf_counter() - invocation_started,
                         "new_trial_seconds_sum": sum(r["elapsed_seconds"] for r in ordered_rows if not r.get("cache_hit")),
                         "engine_seconds_sum": sum(r.get("engine_seconds", 0) for r in ordered_rows if not r.get("cache_hit")),
                         "note": "Worker seconds may overlap; not equal to wall-clock time."}
    summary["failure_kinds"] = sorted({r.get("error_kind", "strategy") for r in ordered_rows if r["status"] == "failed"})
    summary["failure_examples"] = [{"trial_id": r["trial_id"], "kind": r.get("error_kind", "strategy"),
                                    "error": r["error"]} for r in ordered_rows if r["status"] == "failed"][:3]
    if execution_fault is not None:
        summary["status"] = "blocked"
        summary["execution_fault"] = execution_fault
    write_json(output / "summary.json", summary)
    if dependency_manifest(root, spec["factory"], spec) != dependencies:
        # Never let changes made during a batch silently acquire the old identity.
        summary["status"] = "invalid_source_changed"
        summary["warning"] = "shared code changed during execution; rerun under a new source identity"
        with sqlite3.connect(root / ".research/results.sqlite3") as connection:
            connection.executemany("DELETE FROM results WHERE trial_id=?", [(c["trial_id"],) for c in cases])
            connection.execute("DELETE FROM batch_trials WHERE batch_id=?", (batch_id,))
        write_json(output / "summary.json", summary)
    return summary
