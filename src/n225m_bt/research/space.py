"""Finite exhaustive parameter spaces. No sampling, eval, or silent truncation."""
from __future__ import annotations

import hashlib
import itertools
import json
import math
from collections.abc import Iterator, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _scalar(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError(f"parameter values must be finite JSON scalars: {value!r}")


def axis_values(axis: Any) -> tuple[Any, ...]:
    """Expand a list or inclusive {start, stop, step}; decimals avoid float drift."""
    if isinstance(axis, list):
        values = [_scalar(value) for value in axis]
    elif isinstance(axis, dict) and set(axis) == {"start", "stop", "step"}:
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in axis.values()):
            raise ValueError("range bounds and step must be numbers")
        try:
            start, stop, step = (Decimal(str(axis[k])) for k in ("start", "stop", "step"))
            if not all(v.is_finite() for v in (start, stop, step)) or step == 0:
                raise ValueError("range must be finite with a nonzero step")
            if (stop - start) * step < 0:
                raise ValueError("step has the wrong direction")
            count = int((stop - start) // step) + 1
            integer = all(isinstance(v, int) for v in axis.values())
            values = [int(start + i * step) if integer else float(start + i * step)
                      for i in range(count)]
        except (InvalidOperation, OverflowError) as exc:
            raise ValueError("invalid numeric range") from exc
    else:
        raise ValueError("each axis must be a value list or {start, stop, step}")
    unique = {canonical(value): value for value in values}
    if not unique:
        raise ValueError("empty parameter axis")
    return tuple(unique.values())


def expand_axes(space: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    keys = sorted(space)
    if not all(isinstance(key, str) and key for key in keys):
        raise ValueError("parameter names must be nonempty strings")
    values = [axis_values(space[key]) for key in keys]
    for combination in itertools.product(*values):
        yield dict(zip(keys, combination, strict=True))


def matches(parameters: Mapping[str, Any], condition: Mapping[str, Any]) -> bool:
    """Safe comparison; right is a literal, right_param references another axis."""
    left = parameters[condition["left"]]
    if ("right" in condition) == ("right_param" in condition):
        raise ValueError("condition needs exactly one of right or right_param")
    right = parameters[condition["right_param"]] if "right_param" in condition else condition["right"]
    op = condition["op"]
    if op == "eq":
        return bool(left == right)
    if op == "ne":
        return bool(left != right)
    if op == "lt":
        return bool(left < right)
    if op == "le":
        return bool(left <= right)
    if op == "gt":
        return bool(left > right)
    if op == "ge":
        return bool(left >= right)
    if op == "in":
        return left in right
    if op == "not_in":
        return left not in right
    raise ValueError(f"unsupported condition operator: {op}")


def trials(spec: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    """Cartesian products; variants are a union, constraints explicitly remove cases.

    Strategy params and backtest overrides have separate namespaces. Conditions
    see strategy keys directly and execution keys prefixed with `bt.`. Duplicate
    combinations across variants run once. No resource cap changes this iterator.
    """
    variants = spec.get("variants", [{}])
    if not isinstance(variants, list) or not variants:
        raise ValueError("variants must be a nonempty list")
    seen: set[str] = set()
    for index, variant in enumerate(variants):
        if not isinstance(variant, dict):
            raise ValueError(f"variants[{index}] must be a mapping")
        unsupported = set(variant) - {"parameters", "space", "backtest", "backtest_space", "constraints", "id", "name", "description"}
        if unsupported:
            raise ValueError(f"variants[{index}] has unsupported execution fields {sorted(unsupported)}; "
                             "use constraints for conditions and parameters for fixed values; nothing was silently ignored")
        parameters = dict(spec.get("parameters", {})) | variant.get("parameters", {})
        space = dict(spec.get("space", {})) | variant.get("space", {})
        execution = dict(spec.get("backtest", {})) | variant.get("backtest", {})
        execution_space = dict(spec.get("backtest_space", {})) | variant.get("backtest_space", {})
        constraints = list(spec.get("constraints", [])) + variant.get("constraints", [])
        # Flatten only the axes; configured base values remain unchanged.
        combined = space | {f"bt.{k}": v for k, v in execution_space.items()}
        if any(k.startswith("bt.") for k in space):
            raise ValueError("bt. is reserved for backtest overrides")
        for point in expand_axes(combined):
            params = parameters | {k: v for k, v in point.items() if not k.startswith("bt.")}
            backtest = execution | {k[3:]: v for k, v in point.items() if k.startswith("bt.")}
            values = params | {f"bt.{k}": v for k, v in backtest.items()}
            if not all(matches(values, constraint) for constraint in constraints):
                continue
            trial = {"parameters": params, "backtest": backtest}
            key = digest(trial)
            if key not in seen:
                seen.add(key)
                yield trial
