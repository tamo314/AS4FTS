"""Register existing Gold once; read exact files, never ingest or audit inside a batch."""
from __future__ import annotations

import hashlib
import json
import random
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from n225m_bt.config import JST
from n225m_bt.domain import Bar, Session
from n225m_bt.research.space import digest


def safe_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise ValueError("names must contain only letters, digits, dot, dash or underscore")
    return value


def write_json(path: Path, value: object) -> None:
    """Same-filesystem replace: an interrupted write never leaves partial JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                               allow_nan=False, default=str) + "\n", encoding="utf-8")
    temp.replace(path)


def file_hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def register_dataset(root: Path, name: str, gold_root: Path | None = None, *,
                     calendar: Path | None = None, synthetic_days: int = 0) -> Path:
    safe_name(name)
    descriptor: dict[str, Any]
    if synthetic_days:
        if synthetic_days < 1:
            raise ValueError("synthetic_days must be positive")
        descriptor = {"kind": "synthetic", "days": synthetic_days, "seed": 314,
                      "note": "SYNTHETIC DEMONSTRATION, NOT MARKET DATA"}
    else:
        if gold_root is None:
            raise ValueError("provide a Gold root or synthetic_days")
        # Deliberately not **/*.parquet: center must never include root/forward/.
        files = sorted(gold_root.resolve().glob("year=*/month=*/*.parquet"))
        if not files:
            raise ValueError("no year=*/month=*/*.parquet files in the supplied Gold root")
        descriptor = {"kind": "parquet", "files": [
            {"path": str(path), "size": path.stat().st_size,
             "mtime_ns": path.stat().st_mtime_ns, "sha256": file_hash(path)} for path in files
        ]}
    if calendar is not None:
        # Snapshot calendar content, not a mutable reference used by later runs.
        descriptor["calendar"] = {"suffix": calendar.suffix.lower(),
                                  "content": calendar.read_text(encoding="utf-8")}
    descriptor["dataset_id"] = digest(descriptor)
    output = root / ".research/datasets" / f"{name}.json"
    if output.exists():
        previous = json.loads(output.read_text(encoding="utf-8"))
        if previous != descriptor:
            raise ValueError("dataset name already identifies different inputs; use a new name")
    write_json(output, descriptor)
    return output


def load_descriptor(root: Path, name: str) -> dict[str, Any]:
    path = root / ".research/datasets" / f"{safe_name(name)}.json"
    value: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if value.get("dataset_id") != digest({k: v for k, v in value.items() if k != "dataset_id"}):
        raise ValueError("dataset descriptor was changed; register a new snapshot")
    return value


def load_bars(descriptor: dict[str, Any], start: str | None = None,
              end: str | None = None) -> list[Bar]:
    if start and end and start > end:
        raise ValueError("start must not be after end")
    if descriptor["kind"] == "synthetic":
        bars = synthetic_bars(int(descriptor["days"]), int(descriptor["seed"]))
    else:
        import polars as pl
        paths = []
        for item in descriptor["files"]:
            path = Path(item["path"])
            stat = path.stat()
            if (stat.st_size, stat.st_mtime_ns) != (item["size"], item["mtime_ns"]):
                raise ValueError(f"registered file changed: {path}; register a new snapshot")
            paths.append(str(path))
        frame = pl.scan_parquet(paths, hive_partitioning=False)
        if start:
            frame = frame.filter(pl.col("trade_date") >= pl.lit(date.fromisoformat(start)))
        if end:
            frame = frame.filter(pl.col("trade_date") <= pl.lit(date.fromisoformat(end)))
        fields = set(Bar.__dataclass_fields__)
        bars = []
        for row in frame.sort("ts_jst").collect().iter_rows(named=True):
            values = {k: v for k, v in row.items() if k in fields}
            values["session"] = Session(values["session"])
            values["quality_flags"] = tuple(values.get("quality_flags") or ())
            bars.append(Bar(**values))
    result = [bar for bar in bars if (not start or bar.trade_date.isoformat() >= start)
              and (not end or bar.trade_date.isoformat() <= end)]
    if not result:
        raise ValueError("no bars in the requested period")
    return result


def synthetic_bars(days: int = 3, seed: int = 314) -> list[Bar]:
    """Deterministic short day sessions plus a closing bar, for plumbing tests only."""
    rng = random.Random(seed)
    bars: list[Bar] = []
    day = date(2024, 11, 5)
    for _ in range(days):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        price = 40000
        times = [datetime(day.year, day.month, day.day, 9, tzinfo=JST) + timedelta(minutes=i)
                 for i in range(120)]
        times.append(datetime(day.year, day.month, day.day, 15, 40, tzinfo=JST))
        for i, ts in enumerate(times):
            close = price + 5 * rng.choice([-3, -2, -1, 1, 2, 3])
            bars.append(Bar(ts, day, day, Session.DAY, "ose_n225m_from_20241105",
                            price, max(price, close) + 5, min(price, close) - 5,
                            close, 1, i == 0, i == len(times) - 1))
            price = close
        day += timedelta(days=1)
    return bars
