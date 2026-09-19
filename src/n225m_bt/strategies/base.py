"""Strategy plug-in interface limited to available historical bars."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, overload

from n225m_bt.domain import Bar, Signal


class HistoryView(Sequence[Bar]):
    """Read-only, live view of bars observed by the engine so far.

    Reusing this view avoids copying the complete history at every minute while
    preserving the strategy API's read-only sequence contract.
    """

    def __init__(self, bars: list[Bar]) -> None:
        self._bars = bars

    def __len__(self) -> int:
        return len(self._bars)

    @overload
    def __getitem__(self, index: int) -> Bar: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[Bar]: ...

    def __getitem__(self, index: int | slice) -> Bar | Sequence[Bar]:
        return self._bars[index]


@dataclass(frozen=True, slots=True)
class StrategyContext:
    history: Sequence[Bar]
    has_position: bool


class Strategy(Protocol):
    @property
    def strategy_id(self) -> str: ...

    @property
    def strategy_version(self) -> str: ...

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> Signal | None: ...
