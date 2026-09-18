# Architecture Decisions

## ADR-001: Continuous series is research data, not an exact tradable contract history

225Labo center-series data is treated as a continuous research series. It is not assigned a fabricated contract code. `contract_month` is nullable and `series_type=center_continuous`.

## ADR-002: Raw/Bronze/Silver/Gold layers

- Raw: user-downloaded files, immutable.
- Bronze: decoded/parsed source rows with source fields preserved.
- Silver: canonical typed 1-minute bars with session/trade-date metadata.
- Gold: backtest-ready datasets plus derived flags/features.

## ADR-003: Parquet is canonical storage after ingestion

CSV is an interchange/source format only. All repeated research reads use Parquet.

## ADR-004: Time model

`ts_jst` is actual calendar timestamp in Asia/Tokyo. `trade_date` is OSE trading date. Night session bars can have a calendar date earlier than the exchange trade date.

## ADR-005: Versioned session schedules

Trading schedules change over time. Session classification must use effective-date rules, not one current schedule applied to history.

## ADR-006: Conservative OHLC execution

With only OHLC bars, intrabar path is unknown. When stop and target are both touched, V1 assumes the adverse event happens first unless a test explicitly uses a different policy.

## ADR-007: Signal/execution separation

Strategies return desired intent/signals. Execution determines fills, slippage, cost and position transitions.

## ADR-008: Next-bar execution

Signals calculated using close of minute `t` are first eligible for fill at the open of next eligible minute bar `t+1`.

## ADR-009: Integer accounting

N225M price is stored in integer JPY. Tick size is 5 JPY. Contract multiplier is 100 JPY per index point. PnL is stored as integer JPY where possible.

## ADR-010: One-contract V1

V1 uses at most one contract, no pyramiding, no averaging down. Position sizing is a later extension.

## ADR-011: Explicit missing data

Missing minutes are detected and flagged. Do not create synthetic flat bars unless a future feature explicitly requests it and labels them synthetic.

## ADR-012: No third-party backtesting engine in V1

Execution semantics are central to correctness, so V1 uses a small custom engine with transparent event ordering.
