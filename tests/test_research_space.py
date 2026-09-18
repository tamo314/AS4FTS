import pytest
from n225m_bt.research.space import axis_values, digest, trials


def test_decimal_ranges_are_inclusive_and_stable():
    assert axis_values({"start": 0.1, "stop": 0.3, "step": 0.1}) == (0.1, 0.2, 0.3)
    assert axis_values({"start": 3, "stop": 1, "step": -1}) == (3, 2, 1)
    assert axis_values({"start": 0, "stop": 1, "step": 0.3}) == (0.0, 0.3, 0.6, 0.9)


@pytest.mark.parametrize("axis", [[], {"start": 1, "stop": 3, "step": 0},
    {"start": 1, "stop": 3, "step": -1}, [float("nan")], [[1]],
    {"start": True, "stop": 3, "step": 1}])
def test_invalid_axis_is_explicit(axis):
    with pytest.raises(ValueError):
        axis_values(axis)


def test_cartesian_grid_and_execution_axis():
    spec = {"space": {"window": [3, 5, 8], "stop": [2, 4], "target": [4, 8],
                      "direction": ["long", "short"]},
            "backtest_space": {"execution.slippage_ticks": [0, 1]}}
    result = list(trials(spec))
    assert len(result) == len({digest(r) for r in result}) == 48


def test_conditional_variants_and_deduplication():
    spec = {"space": {"fast": [2, 4], "slow": [3, 5]},
            "constraints": [{"left": "fast", "op": "lt", "right_param": "slow"}],
            "variants": [{}, {}, {"parameters": {"exit": "fixed"}}]}
    assert len(list(trials(spec))) == 6


def test_one_constant_case_and_empty_allowed_set():
    assert list(trials({})) == [{"parameters": {}, "backtest": {}}]
    assert list(trials({"space": {"x": [1]}, "constraints": [
        {"left": "x", "op": "gt", "right": 2}]})) == []


def test_hash_not_affected_by_key_order():
    assert digest({"b": 2, "a": 1}) == digest({"a": 1, "b": 2})
