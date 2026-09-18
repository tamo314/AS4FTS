from pathlib import Path
from n225m_bt.components.primitives import RollingMean, RollingRange, tick_bracket
from n225m_bt.domain import Side
from n225m_bt.research.catalog import build_catalog


def test_rolling_features_and_brackets():
    window = RollingRange(2)
    assert window.bounds is None
    window.update(10, 5)
    window.update(12, 7)
    assert window.bounds == (12, 5)
    window.update(9, 6)
    assert window.bounds == (12, 6)
    mean = RollingMean(2)
    assert mean.update(2) is None
    assert mean.update(4) == 3
    assert mean.update(8) == 6
    assert tick_bracket(Side.LONG, 100, 2, 4) == (90, 120)
    assert tick_bracket(Side.SHORT, 100, 2, 4) == (110, 80)


def test_catalog_discovers_new_components_without_importing(tmp_path):
    target = tmp_path / "src/n225m_bt/components/new.py"
    target.parent.mkdir(parents=True)
    target.write_text('raise RuntimeError("must not import")\n'
                      '@component(id="new", kind="feature", summary="discovered")\n'
                      'def reuse(x: int):\n    return x\n')
    catalog = build_catalog(tmp_path)
    assert catalog["components"][0]["id"] == "new"
    assert catalog["components"][0]["signature"] == "reuse(x: int)"


def test_existing_catalog_has_reusable_features():
    entries = build_catalog(Path(__file__).parents[1])["components"]
    assert {"rolling_mean", "rolling_range", "tick_bracket"} <= {e["id"] for e in entries}
