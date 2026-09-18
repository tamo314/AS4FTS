"""Strict, injectable YAML configuration models."""

from __future__ import annotations

from datetime import date, time
from pathlib import Path
from typing import Annotated, Literal, TypeVar
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from n225m_bt.domain import InstrumentSpec, SeriesType

JST = ZoneInfo("Asia/Tokyo")
ModelT = TypeVar("ModelT", bound=BaseModel)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InstrumentFields(StrictModel):
    symbol: Literal["N225M"]
    name: str
    exchange: Literal["OSE"]
    currency: Literal["JPY"]
    timezone: Literal["Asia/Tokyo"]
    price_type: Literal["integer_jpy"]
    contract_multiplier: Annotated[int, Field(gt=0)]
    tick_size: Annotated[int, Field(gt=0)]
    tick_value: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def tick_economics_match(self) -> InstrumentFields:
        if self.tick_size * self.contract_multiplier != self.tick_value:
            raise ValueError("tick_value must equal tick_size * contract_multiplier")
        return self

    def to_spec(self) -> InstrumentSpec:
        return InstrumentSpec(
            self.symbol, self.contract_multiplier, self.tick_size, self.tick_value
        )


class InstrumentConfig(StrictModel):
    schema_version: Literal[1]
    instrument: InstrumentFields


class SessionTimes(StrictModel):
    session_open: time
    session_close: time | None = None
    session_close_next_day: time | None = None
    regular_end: time | None = None
    regular_end_next_day: time | None = None
    closing_auction: time | None = None
    closing_auction_next_day: time | None = None

    @model_validator(mode="after")
    def exactly_one_close(self) -> SessionTimes:
        if (self.session_close is None) == (self.session_close_next_day is None):
            raise ValueError("specify exactly one of session_close/session_close_next_day")
        return self


class SessionRegime(StrictModel):
    id: str
    effective_from: date
    effective_to: date | None = None
    day: SessionTimes
    night: SessionTimes

    @model_validator(mode="after")
    def sessions_have_expected_direction(self) -> SessionRegime:
        if self.day.session_close is None or self.night.session_close_next_day is None:
            raise ValueError("day must close same day and night must close next day")
        return self


class SessionsConfig(StrictModel):
    schema_version: Literal[1]
    timezone: Literal["Asia/Tokyo"]
    instrument: Literal["N225M"]
    regimes: tuple[SessionRegime, ...]

    @model_validator(mode="after")
    def ranges_do_not_overlap(self) -> SessionsConfig:
        ordered = sorted(self.regimes, key=lambda item: item.effective_from)
        if tuple(ordered) != self.regimes:
            raise ValueError("regimes must be ordered by effective_from")
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if previous.effective_to is None or previous.effective_to >= current.effective_from:
                raise ValueError("session effective ranges overlap")
        return self


class SourceFormat(StrictModel):
    worksheet: str = "1min"
    encoding: str = "auto"
    delimiter: str = "auto"
    header: str | bool = "auto"
    source_date_semantics: Literal["actual_calendar_date", "ose_trade_date"] = "ose_trade_date"
    source_mapping: str | dict[str, str] = "auto"


class QualityConfig(StrictModel):
    mode: Literal["strict", "permissive"] = "strict"
    tick_grid_check: bool = True
    expected_tick_size: Annotated[int, Field(gt=0)] = 5
    detect_missing_minutes: bool = True
    detect_statistical_outliers: bool = True
    outlier_return_sigma: Annotated[float, Field(gt=0)] = 12.0


class ParquetConfig(StrictModel):
    compression: Literal["zstd", "snappy", "lz4", "uncompressed"] = "zstd"
    partition_by: tuple[Literal["year", "month"], ...] = ("year", "month")


class DataConfig(StrictModel):
    schema_version: Literal[1]
    source: Literal["225labo"]
    instrument: Literal["N225M"]
    series_type: SeriesType
    bar_interval: Literal["1m"]
    raw_root: Path
    bronze_root: Path
    silver_root: Path
    gold_root: Path
    source_format: SourceFormat = SourceFormat()
    quality: QualityConfig = QualityConfig()
    parquet: ParquetConfig = ParquetConfig()


class PositionConfig(StrictModel):
    quantity: Literal[1]
    max_open_positions: Literal[1]
    pyramiding: Literal[False]
    averaging_down: Literal[False]


class ExecutionConfig(StrictModel):
    signal_timing: Literal["bar_close"]
    market_fill_timing: Literal["next_eligible_bar_open"]
    slippage_ticks: Annotated[int, Field(ge=0)] = 1
    intrabar_policy: Literal["conservative"] = "conservative"
    max_fill_delay_minutes: Annotated[int, Field(ge=0)] = 10
    allow_cross_session_pending_order: bool = False
    reverse_policy: Literal["close_only_then_wait"] = "close_only_then_wait"


class RiskConfig(StrictModel):
    new_entry_cutoff_minutes_before_session_close: Annotated[int, Field(ge=0)] = 15
    force_flat: bool = True
    force_flat_minutes_before_session_close: Annotated[int, Field(ge=0)] = 5


class FeeConfig(StrictModel):
    model: Literal["per_side_per_contract"]
    jpy_per_side_per_contract: Annotated[int, Field(ge=0)] = 0


class ReportingConfig(StrictModel):
    slippage_stress_ticks: tuple[Annotated[int, Field(ge=0)], ...] = (0, 1, 2, 3)
    segments: tuple[str, ...] = ()


class BacktestConfig(StrictModel):
    schema_version: Literal[1]
    instrument: Literal["N225M"]
    mode: Literal["day_only", "night_only", "full_session"]
    position: PositionConfig
    execution: ExecutionConfig
    risk: RiskConfig
    fees: FeeConfig
    reporting: ReportingConfig


class DateRange(StrictModel):
    start: date
    end: date

    @model_validator(mode="after")
    def date_order_is_valid(self) -> DateRange:
        if self.start > self.end:
            raise ValueError("start must not be after end")
        return self


class WalkForwardConfig(StrictModel):
    enabled: bool
    train_months: Annotated[int, Field(gt=0)]
    test_months: Annotated[int, Field(gt=0)]
    step_months: Annotated[int, Field(gt=0)]


class ResearchConfig(StrictModel):
    schema_version: Literal[1]
    splits: dict[str, DateRange]
    walk_forward: WalkForwardConfig


def load_yaml_model(path: Path, model: type[ModelT]) -> ModelT:
    """Load one YAML file and reject malformed or unknown configuration."""
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"cannot read configuration {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"configuration {path} must contain a YAML mapping")
    try:
        return model.model_validate(payload)
    except ValidationError as error:
        raise ValueError(f"invalid configuration {path}: {error}") from error


def load_project_config(
    config_dir: Path,
) -> tuple[InstrumentConfig, SessionsConfig, DataConfig, BacktestConfig]:
    return (
        load_yaml_model(config_dir / "instrument.yaml", InstrumentConfig),
        load_yaml_model(config_dir / "sessions.yaml", SessionsConfig),
        load_yaml_model(config_dir / "data.yaml", DataConfig),
        load_yaml_model(config_dir / "backtest.yaml", BacktestConfig),
    )


def load_research_config(config_dir: Path) -> ResearchConfig:
    return load_yaml_model(config_dir / "research.yaml", ResearchConfig)
