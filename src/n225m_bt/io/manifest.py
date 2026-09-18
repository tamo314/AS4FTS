"""Stable data/run identity built from canonical JSON content."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


def canonical_hash(payload: object) -> str:
    rendered = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    schema_version: int
    source_hashes: tuple[str, ...]
    source_adapter_version: str
    normalization_config_hash: str
    earliest_ts: str | None
    latest_ts: str | None
    row_count: int
    quality_summary: dict[str, object]

    @property
    def dataset_id(self) -> str:
        return canonical_hash(asdict(self))

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self) | {"dataset_id": self.dataset_id}
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    @classmethod
    def from_path(cls, path: Path) -> DatasetManifest:
        """Load a manifest previously created by :meth:`write`."""
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        payload.pop("dataset_id", None)
        payload["source_hashes"] = tuple(payload["source_hashes"])
        return cls(**payload)


def merge_dataset_manifests(manifests: list[DatasetManifest]) -> DatasetManifest:
    """Combine independently ingested source manifests into one dataset identity."""
    if not manifests:
        raise ValueError("cannot merge an empty set of dataset manifests")
    adapter_versions = {item.source_adapter_version for item in manifests}
    config_hashes = {item.normalization_config_hash for item in manifests}
    if len(adapter_versions) != 1 or len(config_hashes) != 1:
        raise ValueError(
            "cannot merge manifests made with different adapters or normalization config"
        )
    return DatasetManifest(
        schema_version=max(item.schema_version for item in manifests),
        source_hashes=tuple(
            sorted({source for item in manifests for source in item.source_hashes})
        ),
        source_adapter_version=next(iter(adapter_versions)),
        normalization_config_hash=next(iter(config_hashes)),
        earliest_ts=min(item.earliest_ts for item in manifests if item.earliest_ts is not None),
        latest_ts=max(item.latest_ts for item in manifests if item.latest_ts is not None),
        row_count=sum(item.row_count for item in manifests),
        quality_summary=_merge_quality_summaries([item.quality_summary for item in manifests]),
    )


def _merge_quality_summaries(summaries: list[dict[str, object]]) -> dict[str, object]:
    merged: dict[str, object] = {"issue_count": 0}
    for summary in summaries:
        issue_count = summary["issue_count"]
        if not isinstance(issue_count, int):
            raise ValueError("invalid manifest quality summary issue_count")
        current_count = merged["issue_count"]
        if not isinstance(current_count, int):
            raise AssertionError("quality summary aggregation type invariant failed")
        merged["issue_count"] = current_count + issue_count
        for key in ("by_code", "by_severity", "by_year", "by_month", "by_session"):
            counts = summary[key]
            if not isinstance(counts, dict):
                raise ValueError(f"invalid manifest quality summary field {key}")
            destination = merged.setdefault(key, {})
            if not isinstance(destination, dict):
                raise AssertionError("quality summary aggregation type invariant failed")
            for name, count in counts.items():
                destination[str(name)] = int(destination.get(str(name), 0)) + int(count)
    return merged
