"""Small file-based objectives, snapshotted once per design; no approval gate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def resolve_objective(root: Path, config: dict[str, Any], step: Path) -> str:
    """Append a UTF-8 objective file to the campaign objective, resolving from root.

    A resumed design uses its saved text even if the original file was edited.
    Change campaign_id to start a different prompt, rather than mutating history.
    No data access, model invocation, or hypothesis approval is performed here.
    """
    objective = config.get("objective", "Develop and test strategy families")
    if not isinstance(objective, str):
        raise ValueError("objective must be a string")
    name = config.get("objective_file")
    if not name:
        return objective
    if not isinstance(name, str):
        raise ValueError("objective_file must be a path string")
    snapshot = step / "objective_snapshot.json"
    if snapshot.exists():
        return str(json.loads(snapshot.read_text(encoding="utf-8"))["resolved_objective"])
    path = (root / name).resolve()
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        raise ValueError(f"objective_file is empty: {path}")
    resolved = objective + "\n\n" + text
    payload = {"path": str(path), "sha256": hashlib.sha256(text.encode()).hexdigest(),
               "text": text, "resolved_objective": resolved}
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    temp = snapshot.with_name(snapshot.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(snapshot)
    return resolved
