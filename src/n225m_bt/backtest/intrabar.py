"""Explicit conservative OHLC stop/target resolution."""

from __future__ import annotations

from dataclasses import dataclass

from n225m_bt.domain import Bar, ExitReason, Position, Side


@dataclass(frozen=True, slots=True)
class ProtectiveExit:
    reason: ExitReason
    reference_price: int


def protective_exit(position: Position, bar: Bar) -> ProtectiveExit | None:
    stop_hit = position.stop_price is not None and (
        (position.side is Side.LONG and bar.low <= position.stop_price)
        or (position.side is Side.SHORT and bar.high >= position.stop_price)
    )
    target_hit = position.target_price is not None and (
        (position.side is Side.LONG and bar.high >= position.target_price)
        or (position.side is Side.SHORT and bar.low <= position.target_price)
    )
    if not stop_hit and not target_hit:
        return None
    # Conservative policy: simultaneous OHLC reachability resolves to stop.
    if stop_hit:
        assert position.stop_price is not None
        gap_worse = (position.side is Side.LONG and bar.open < position.stop_price) or (
            position.side is Side.SHORT and bar.open > position.stop_price
        )
        return ProtectiveExit(ExitReason.STOP, bar.open if gap_worse else position.stop_price)
    assert position.target_price is not None
    return ProtectiveExit(ExitReason.TARGET, position.target_price)
