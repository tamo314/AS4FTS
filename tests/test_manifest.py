from __future__ import annotations

from n225m_bt.io.manifest import DatasetManifest, merge_dataset_manifests


def test_merged_dataset_manifest_preserves_all_source_lineage() -> None:
    first = DatasetManifest(
        1,
        ("a",),
        "2",
        "config",
        "2024-01-01T00:00:00+09:00",
        "2024-01-01T01:00:00+09:00",
        2,
        {
            "issue_count": 1,
            "by_code": {"A": 1},
            "by_severity": {"WARN": 1},
            "by_year": {"2024": 1},
            "by_month": {"2024-01": 1},
            "by_session": {"day": 1},
        },
    )
    second = DatasetManifest(
        1,
        ("b",),
        "2",
        "config",
        "2024-02-01T00:00:00+09:00",
        "2024-02-01T01:00:00+09:00",
        3,
        {
            "issue_count": 2,
            "by_code": {"B": 2},
            "by_severity": {"WARN": 2},
            "by_year": {"2024": 2},
            "by_month": {"2024-02": 2},
            "by_session": {"night": 2},
        },
    )
    merged = merge_dataset_manifests([first, second])
    assert merged.source_hashes == ("a", "b")
    assert merged.row_count == 5
    assert merged.quality_summary["by_severity"] == {"WARN": 3}
