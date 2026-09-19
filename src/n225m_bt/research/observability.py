"""Post-run diagnostics and timings; no strategy approval or market-data audit."""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from time import perf_counter
from typing import Any, TypeVar

T = TypeVar('T')


def timed_call(state: dict[str, Any], phase: str, action: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    start = perf_counter()
    try:
        return action(*args, **kwargs)
    finally:
        elapsed = perf_counter() - start
        total = state.setdefault('phase_seconds', {})
        total[phase] = total.get(phase, 0) + elapsed
        active = state.get('active')
        if active is not None:
            local = active.setdefault('phase_seconds', {})
            local[phase] = local.get(phase, 0) + elapsed


def strategy_diagnostics(strategy: Any) -> dict[str, Any]:
    """Bounded explanation of existing diagnostic state; never infer missing counts."""
    try:
        value = getattr(strategy, 'diagnostics', None)
        if value is None:
            return {'available': False}
        if callable(value):
            value = value()
        if not isinstance(value, dict):
            return {'available': False, 'warning': 'diagnostics is not a mapping'}
        reasons = Counter(str(v) for v in value.values())
        return {'available': True, 'records': len(value), 'reason_counts': dict(reasons),
                'examples': [{'key': str(k), 'value': str(v)} for k, v in list(value.items())[:5]],
                'note': 'Strategy-reported diagnostics, not independently classified market events.'}
    except Exception as exc:
        return {'available': False, 'warning': f'diagnostic export failed: {exc}'}
