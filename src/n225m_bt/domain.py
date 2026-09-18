"""Stable domain primitives shared across data and execution layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - supports local verification on Python 3.10

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        pass


class Session(StrEnum):
    DAY = "day"
    NIGHT = "night"


class Side(StrEnum):
    LONG = "long"
    SHORT = "short"

    @property
    def sign(self) -> int:
        return 1 if self is Side.LONG else -1

    @property
    def close_is_sell(self) -> bool:
        return self is Side.LONG


class OrderType(StrEnum):
    MARKET = "market"
    STOP = "stop"
    TARGET = "target"


class ExitReason(StrEnum):
    SIGNAL = "signal"
    STOP = "stop"
    TARGET = "target"
    FORCE_FLAT = "force_flat"
    END_OF_DATA = "end_of_data"


class SeriesType(StrEnum):
    CENTER_CONTINUOUS = "center_continuous"
    NEXT_CONTINUOUS = "next_continuous"
    CONTRACT = "contract"


class SignalAction(StrEnum):
    ENTER_LONG = "enter_long"
    ENTER_SHORT = "enter_short"
    EXIT = "exit"


@dataclass(frozen=True, slots=True)
class InstrumentSpec:
    symbol: str
    multiplier: int
    tick_size: int
    tick_value: int

    def __post_init__(self) -> None:
        if self.multiplier <= 0 or self.tick_size <= 0 or self.tick_value <= 0:
            raise ValueError("instrument multiplier, tick size, and tick value must be positive")
        if self.tick_size * self.multiplier != self.tick_value:
            raise ValueError("tick_value must equal tick_size * contract_multiplier")


@dataclass(frozen=True, slots=True)
class Bar:
    ts_jst: datetime
    trade_date: date
    calendar_date: date
    session: Session
    schedule_version: str
    open: int
    high: int
    low: int
    close: int
    volume: int | None = None
    is_session_open: bool = False
    is_session_close: bool = False
    is_missing_prev_expected: bool = False
    roll_risk: bool = False
    is_eligible: bool = True
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Signal:
    action: SignalAction
    timestamp: datetime
    stop_price: int | None = None
    target_price: int | None = None
    reason: str = "strategy"


@dataclass(slots=True)
class Position:
    side: Side
    qty: int
    entry_ts: datetime
    entry_signal_ts: datetime
    entry_reference_price: int
    entry_fill_price: int
    trade_date: date
    stop_price: int | None = None
    target_price: int | None = None
    mae_price_delta: int = 0
    mfe_price_delta: int = 0
    entry_reason: str = "signal"
    entry_session: Session | None = None
    entry_roll_risk: bool = False


@dataclass(frozen=True, slots=True)
class Trade:
    trade_id: str
    trade_date: date
    side: Side
    qty: int
    entry_signal_ts: datetime
    entry_ts: datetime
    entry_reference_price: int
    entry_fill_price: int
    exit_signal_ts: datetime | None
    exit_ts: datetime
    exit_reference_price: int
    exit_fill_price: int
    gross_pnl_jpy: int
    fees_jpy: int
    slippage_cost_jpy: int
    net_pnl_jpy: int
    mae_jpy: int
    mfe_jpy: int
    holding_minutes: int
    entry_reason: str
    exit_reason: ExitReason
    strategy_id: str
    strategy_version: str
    parameter_hash: str
    metadata: dict[str, object] = field(default_factory=dict)
