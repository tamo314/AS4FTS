"""Adapter for already configured CLI agents. No provider SDK or installation logic."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from n225m_bt.research.datasets import file_hash, write_json
from n225m_bt.research.space import digest


def run_process(argv: list[str], root: Path, stdout: Path, stderr: Path, *,
                prompt: str = "", timeout: float | None = None,
                extra_env: dict[str, str] | None = None) -> int:
    """No shell interpolation. On timeout kill this invocation's process tree."""
    stdout.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ) | (extra_env or {})
    with stdout.open("w", encoding="utf-8") as out, stderr.open("w", encoding="utf-8") as err:
        process = subprocess.Popen(argv, cwd=root, env=env, stdin=subprocess.PIPE,
                                   stdout=out, stderr=err, text=True, encoding="utf-8",
                                   start_new_session=os.name != "nt")
        try:
            process.communicate(prompt, timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.communicate()
            raise
        return int(process.returncode)


def decode_payload(text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Accept plain JSON, fenced JSON, Claude result envelopes or final JSONL events."""
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        text = "\n".join(text.splitlines()[1:-1])
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        candidates = []
        for line in text.splitlines():
            try:
                candidates.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if not candidates:
            raise ValueError("agent did not return JSON") from None
        for candidate in reversed(candidates):
            if isinstance(candidate, dict) and ("structured_output" in candidate or "result" in candidate):
                return decode_payload(json.dumps(candidate))
            if isinstance(candidate, dict) and candidate.get("item", {}).get("type") == "agent_message":
                return decode_payload(candidate["item"]["text"])
        raise ValueError("no final structured result in agent events") from None
    if not isinstance(raw, dict):
        raise ValueError("agent output must be a JSON object")
    metadata = {"usage": raw.get("usage"), "reported_cost_usd": raw.get("total_cost_usd"),
                "model": raw.get("model"), "session_id": raw.get("session_id")}
    if isinstance(raw.get("structured_output"), dict):
        return raw["structured_output"], metadata
    if isinstance(raw.get("result"), str):
        payload, _ = decode_payload(raw["result"])
        return payload, metadata
    return raw, metadata


def build_arguments(role: dict[str, Any], prompt: str, output: Path) -> list[str]:
    """Bind YAML role.model without requiring shell environment variables.

    A null/blank model uses the CLI's configured default by removing the explicit
    --model/-m pair. Legacy ${AS4FTS_*_MODEL} templates remain supported; a direct
    model value takes precedence. Substitution never interprets prompt contents.
    """
    template = role.get("argv")
    if not isinstance(template, list) or not template or not all(isinstance(a, str) for a in template):
        raise ValueError("role.argv must be a nonempty string array")
    model = role.get("model")
    if model is not None and not isinstance(model, str):
        raise ValueError("role.model must be a model ID string or null")
    model = model.strip() if isinstance(model, str) else None
    model = model or None
    legacy = ("${AS4FTS_DESIGN_MODEL}", "${AS4FTS_IMPLEMENT_MODEL}")
    tokens = list(template)
    if model is not None:
        tokens = [token.replace(legacy[0], "{model}").replace(legacy[1], "{model}") for token in tokens]
        if not any("{model}" in token for token in tokens):
            raise ValueError("role.model is set but role.argv has no {model} placeholder")
    arguments: list[str] = []
    replacements = {"prompt": prompt, "output": str(output), "model": model or ""}
    for token in tokens:
        if "{model}" in token and model is None:
            if token == "{model}" and arguments and arguments[-1] in {"--model", "-m"}:
                arguments.pop()
                continue
            if token == "--model={model}":
                continue
            raise ValueError("null role.model requires --model {model}, -m {model}, or --model={model}")
        expanded = os.path.expandvars(token)
        if re.search(r"\$\{[^}]+\}", expanded):
            raise ValueError(f"unresolved environment variable in command: {token}")
        arguments.append(re.sub(r"\{(prompt|output|model)\}",
                                lambda match: replacements[match.group(1)], expanded))
    return arguments


def invoke_role(role: dict[str, Any], prompt: str, root: Path,
                folder: Path) -> dict[str, Any]:
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / "output.json"
    template = role["argv"]
    arguments = build_arguments(role, prompt, output)
    request_id = digest({"argv": arguments, "prompt": prompt})
    response_file = folder / "response.json"
    if response_file.exists():
        old = json.loads(response_file.read_text(encoding="utf-8"))
        if old["request_id"] == request_id:
            return dict(old["payload"])
    output.unlink(missing_ok=True)
    (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
    start = time.perf_counter()
    code = run_process(arguments, root, folder / "stdout.log", folder / "stderr.log",
                       prompt=prompt if role.get("stdin", not any("{prompt}" in t for t in template)) else "",
                       timeout=role.get("timeout_seconds"))
    if code:
        raise RuntimeError(f"CLI exited {code}; see {folder / 'stderr.log'}")
    text = output.read_text(encoding="utf-8") if output.exists() else (folder / "stdout.log").read_text(encoding="utf-8")
    payload, metadata = decode_payload(text)
    write_json(response_file, {"request_id": request_id, "payload": payload,
                              "elapsed_seconds": time.perf_counter() - start,
                              "metadata": metadata,
                              "requested_model": role.get("model"),
                              "note": "Unreported costs/usage are unknown, never assumed zero."})
    return payload


def apply_files(payload: dict[str, Any], root: Path, folder: Path) -> list[dict[str, Any]]:
    """Apply reusable library/strategy code only, with backups; no review gate."""
    root = root.resolve()
    allowed = [(root / "src/n225m_bt/components").resolve(),
               (root / "src/n225m_bt/strategies").resolve()]
    items = payload.get("files", [])
    if not isinstance(items, list):
        raise ValueError("implementation files must be an array")
    planned = []
    for item in items:
        path = (root / item["path"]).resolve()
        if not path.is_relative_to(root) or path.suffix != ".py" or not any(path.is_relative_to(base) for base in allowed):
            raise ValueError(f"research implementation cannot write {item['path']}")
        if not isinstance(item["content"], str):
            raise ValueError("file content must be UTF-8 text")
        planned.append((path, item["content"]))
    changes = []
    for path, content in planned:
        relative = path.relative_to(root)
        before = file_hash(path) if path.exists() else None
        if path.exists():
            backup = folder / "before" / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(path.read_bytes())
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(content, encoding="utf-8")
        temp.replace(path)
        Path(importlib.util.cache_from_source(str(path))).unlink(missing_ok=True)
        changes.append({"path": relative.as_posix(), "before": before, "after": file_hash(path)})
    write_json(folder / "changes.json", changes)
    return changes
