"""Deliberately non-alpha strategies for engine verification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from n225m_bt.domain import Bar, Signal, SignalAction
from n225m_bt.strategies.base import StrategyContext


@dataclass(frozen=True, slots=True)
class AlwaysFlatStrategy:
    strategy_id: str = "always_flat"
    strategy_version: str = "1"

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> Signal | None:
        return None


@dataclass(frozen=True, slots=True)
class TimestampSignalStrategy:
    entries: dict[datetime, SignalAction]
    strategy_id: str = "timestamp_signal"
    strategy_version: str = "1"

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> Signal | None:
        action = self.entries.get(bar.ts_jst)
        return Signal(action, bar.ts_jst) if action is not None else None
