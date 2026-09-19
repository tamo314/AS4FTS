"""Campaign-wide research memory built from small saved summaries, not market data."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from n225m_bt.research.space import canonical


def _compact(spec: dict[str, Any], summary: dict[str, Any], path: Path,
             campaign: str | None = None) -> dict[str, Any]:
    identity = summary.get("identity", {})
    axes = {key: spec[key] for key in ("parameters", "space", "backtest", "backtest_space",
                                     "variants", "constraints", "periods", "start", "end") if key in spec}
    return {"family_id": identity.get("family_id", spec.get("family_id")),
            "batch_id": identity.get("batch_id"), "campaign_id": campaign,
            "factory": spec.get("factory"), "dataset": spec.get("dataset"),
            "dataset_id": identity.get("dataset_id"), "source_id": identity.get("source_id"),
            "hypothesis": str(spec.get("hypothesis", identity.get("hypothesis", "")))[:1800],
            "tested_space": axes, "uses": spec.get("uses", []),
            "status": summary.get("status"), "coverage": summary.get("coverage"),
            "distribution": summary.get("distribution"),
            "diagnostics": summary.get("diagnostics_summary"),
            "source": str(path), "evidence_type": "saved_result_summary",
            "note": "Previously observed exploration; not independent confirmation. Inspect source for full evidence."}


def refresh_index(root: Path) -> list[str]:
    """Index changed metadata only. A failed optional index never starts a data audit."""
    base = root / ".research"
    base.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    with sqlite3.connect(base / "research_index.sqlite3", timeout=5) as db:
        db.execute("CREATE TABLE IF NOT EXISTS documents(path TEXT PRIMARY KEY, stamp TEXT, records TEXT)")
        paths = sorted((base / "batches").glob("*/*/summary.json"))
        paths += sorted((base / "campaigns").glob("*/state.json"))
        for path in paths:
            try:
                spec_path = path.with_name("family.json")
                watched = [path] + ([spec_path] if spec_path.exists() else [])
                stamp = canonical([(str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in watched])
                previous = db.execute("SELECT stamp FROM documents WHERE path=?", (str(path),)).fetchone()
                if previous and previous[0] == stamp:
                    continue
                data = json.loads(path.read_text(encoding="utf-8-sig"))
                records = []
                if path.name == "summary.json":
                    spec = json.loads(spec_path.read_text(encoding="utf-8-sig")) if spec_path.exists() else {}
                    records.append(_compact(spec, data, path))
                else:
                    for entry in data.get("history", []):
                        family_path = path.parent / entry["family_id"] / "family.json"
                        spec = json.loads(family_path.read_text(encoding="utf-8-sig")) if family_path.exists() else entry
                        if entry.get("summary"):
                            record = _compact(spec, entry["summary"], path, data.get("campaign_id"))
                        else:
                            record = {"family_id": entry["family_id"], "campaign_id": data.get("campaign_id"),
                                      "status": entry.get("status", "failed"), "factory": spec.get("factory"),
                                      "dataset": spec.get("dataset"), "error": str(entry.get("error", ""))[:1800],
                                      "source": str(path), "evidence_type": "saved_failure"}
                        records.append(record)
                db.execute("INSERT OR REPLACE INTO documents VALUES(?,?,?)", (str(path), stamp, canonical(records)))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                warnings.append(f"{path}: {exc}")
    return warnings


def related_history(root: Path, objective: str, dataset: str, *, campaign: str = "",
                    limit: int = 8) -> dict[str, Any]:
    """Small deterministic relevance selection, never ranked by best profit."""
    try:
        warnings = refresh_index(root)
        with sqlite3.connect(root / ".research/research_index.sqlite3", timeout=5) as db:
            stored = db.execute("SELECT path, records FROM documents ORDER BY path").fetchall()
        unique: dict[str, dict[str, Any]] = {}
        for path, encoded in stored:
            if not Path(path).exists():
                continue
            for record in json.loads(encoded):
                if campaign and (record.get("campaign_id") == campaign or
                                 str(record.get("family_id", "")).startswith(campaign + "-")):
                    continue
                key = record.get("batch_id") or record.get("family_id")
                # Prefer a direct, existing batch summary over a campaign copy.
                if key not in unique or Path(path).name == "summary.json":
                    unique[key] = record
        words = set(re.findall(r"[A-Za-z_]{3,}|[\u3040-\u9fff]{2,}", objective.casefold()))
        def score(record: dict[str, Any]) -> tuple[int, str]:
            text = canonical(record).casefold()
            return (20 * (record.get("dataset") == dataset) + sum(w in text for w in words),
                    str(record.get("family_id", "")))
        selected = sorted(unique.values(), key=score, reverse=True)[:max(0, limit)]
        return {"records": selected, "indexed_families": len(unique), "warnings": warnings,
                "scope": "all locally saved campaigns and batch summaries; no source prices read"}
    except (OSError, sqlite3.Error, ValueError) as exc:
        return {"records": [], "warnings": [f"optional research history unavailable: {exc}"],
                "indexed_families": 0}
