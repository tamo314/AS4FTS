"""Adapter for already configured CLI agents. No provider SDK or installation logic."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import signal
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from n225m_bt.research.agent_output import decode_payload, encode_stdin
from n225m_bt.research.datasets import file_hash, write_json
from n225m_bt.research.space import digest
from n225m_bt.research.faults import AgentCommandError
from n225m_bt.research.storage import atomic_text


def run_process(argv: list[str], root: Path, stdout: Path, stderr: Path, *,
                prompt: str = "", timeout: float | None = None,
                extra_env: dict[str, str] | None = None) -> int:
    """No shell interpolation. On timeout kill this invocation's process tree."""
    stdout.parent.mkdir(parents=True, exist_ok=True)
    root = root.resolve()
    env = dict(os.environ) | (extra_env or {})
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    if not argv:
        raise AgentCommandError("empty command")
    executable = shutil.which(argv[0], path=env.get("PATH"))
    if executable is None:
        candidate = (root / argv[0]).resolve()
        if not candidate.is_file():
            raise AgentCommandError(f"executable not found: {argv[0]}; configure a resolved CLI path")
        executable = str(candidate)
    argv = [executable, *argv[1:]]
    write_json(stdout.with_name(stdout.name + ".process.json"),
               {"executable": executable, "cwd": str(root), "timeout_seconds": timeout})
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


def build_arguments(role: dict[str, Any], prompt: str, output: Path,
                    root: Path | None = None) -> list[str]:
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
    replacements = {"prompt": prompt, "output": str(output), "model": model or "", "root": str((root or Path.cwd()).resolve())}
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
        arguments.append(re.sub(r"\{(prompt|output|model|root)\}",
                                lambda match: replacements[match.group(1)], expanded))
    return arguments


def invoke_role(role: dict[str, Any], prompt: str, root: Path,
                folder: Path) -> dict[str, Any]:
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / "output.json"
    template = role["argv"]
    arguments = build_arguments(role, prompt, output, root)
    uses_stdin = role.get("stdin", not any("{prompt}" in t for t in template))
    if role.get("stdin_format", "text") != "text" and not uses_stdin:
        raise ValueError("structured stdin requires role.stdin: true")
    input_text = encode_stdin(prompt, role) if uses_stdin else ""
    request_id = digest({"argv": arguments, "prompt": prompt,
                         "stdin_format": role.get("stdin_format", "text"), "decoder_version": 2})
    response_file = folder / "response.json"
    if response_file.exists():
        old = json.loads(response_file.read_text(encoding="utf-8"))
        if old["request_id"] == request_id:
            return dict(old["payload"])
    receipt_file = folder / "receipt.json"
    receipt = json.loads(receipt_file.read_text(encoding="utf-8")) if receipt_file.exists() else {}
    reuse_raw = receipt.get("request_id") == request_id and receipt.get("returncode") == 0
    elapsed = float(receipt.get("elapsed_seconds", 0)) if reuse_raw else 0.0
    if not reuse_raw:
        output.unlink(missing_ok=True)
        atomic_text(folder / "prompt.txt", prompt)
        start = time.perf_counter()
        code = run_process(arguments, root, folder / "stdout.log", folder / "stderr.log",
                           prompt=input_text, timeout=role.get("timeout_seconds"))
        elapsed = time.perf_counter() - start
        write_json(receipt_file, {"request_id": request_id, "returncode": code,
                                 "elapsed_seconds": elapsed})
        if code:
            raise AgentCommandError(f"CLI exited {code}; see {folder / 'stderr.log'}")
    text = output.read_text(encoding="utf-8-sig") if output.exists() else (folder / "stdout.log").read_text(encoding="utf-8-sig")
    payload, metadata = decode_payload(text)
    write_json(response_file, {"request_id": request_id, "payload": payload,
                              "elapsed_seconds": elapsed, "recovered_saved_output": reuse_raw,
                              "metadata": metadata,
                              "requested_model": role.get("model"),
                              "note": "Unreported costs/usage are unknown, never assumed zero."})
    return payload


def apply_files(payload: dict[str, Any], root: Path, folder: Path) -> list[dict[str, Any]]:
    """Apply reusable library/strategy code only, with backups; no review gate."""
    root = root.resolve()
    allowed = [(root / "src/n225m_bt/components").resolve(),
               (root / "src/n225m_bt/strategies").resolve()]
    if "files" not in payload:
        raise ValueError("implementation response is missing files; expected decoded code JSON")
    items = payload["files"]
    if not isinstance(items, list):
        raise ValueError("implementation files must be an array")
    planned = []
    for item in items:
        path = (root / item["path"]).resolve()
        if path == root / "src/n225m_bt/strategies/base.py":
            raise ValueError("strategy API changes belong to infrastructure work, not generated strategies")
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
        atomic_text(path, content)
        Path(importlib.util.cache_from_source(str(path))).unlink(missing_ok=True)
        changes.append({"path": relative.as_posix(), "before": before, "after": file_hash(path)})
    write_json(folder / "changes.json", changes)
    return changes
