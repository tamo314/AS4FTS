import json
from dataclasses import asdict

import pytest

from n225m_bt.research.datasets import load_bars, load_descriptor, register_dataset, synthetic_bars


def test_registration_selects_only_the_requested_series(tmp_path):
    center = tmp_path / "gold/year=2024/month=11/bars.parquet"
    forward = tmp_path / "gold/forward/year=2024/month=11/bars.parquet"
    center.parent.mkdir(parents=True)
    forward.parent.mkdir(parents=True)
    center.write_bytes(b"registration test, no market data")
    forward.write_bytes(b"must not be selected")
    register_dataset(tmp_path, "center", tmp_path / "gold")
    descriptor = load_descriptor(tmp_path, "center")
    assert [item["path"] for item in descriptor["files"]] == [str(center)]
    assert register_dataset(tmp_path, "center", tmp_path / "gold").exists()


def test_dataset_names_are_immutable_and_descriptor_changes_detected(tmp_path):
    path = register_dataset(tmp_path, "demo", synthetic_days=1)
    with pytest.raises(ValueError, match="new name"):
        register_dataset(tmp_path, "demo", synthetic_days=2)
    value = json.loads(path.read_text())
    value["days"] = 3
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="descriptor"):
        load_descriptor(tmp_path, "demo")


def test_real_parquet_reader_and_changed_file_detection(tmp_path):
    pl = pytest.importorskip("polars", reason="real Parquet test requires project dependencies")
    bars = synthetic_bars(1)
    rows = [{**asdict(bar), "session": bar.session.value, "quality_flags": list(bar.quality_flags)} for bar in bars]
    path = tmp_path / "gold/year=2024/month=11/bars.parquet"
    path.parent.mkdir(parents=True)
    pl.DataFrame(rows).write_parquet(path)
    register_dataset(tmp_path, "center", tmp_path / "gold")
    descriptor = load_descriptor(tmp_path, "center")
    loaded = load_bars(descriptor, "2024-11-05", "2024-11-05")
    assert loaded == bars
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="registered file changed"):
        load_bars(descriptor)
