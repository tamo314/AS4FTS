# 01. Scope and Requirements

## 1. Target instrument

- Product: Nikkei 225 mini futures
- Internal symbol: `N225M`
- Currency: JPY
- Time zone: `Asia/Tokyo`
- Contract unit: Nikkei 225 × 100 JPY
- Tick size: 5 JPY
- Tick value: 500 JPY per contract

## 2. Initial data source

225Labo, 1-minute center-contract continuous series, user-downloaded.

Target initial history: 2021 through latest available year. The implementation must support older years without structural changes.

Optional second series: 225Labo 3-month-ahead series. It is stored independently and is not required for the first backtest.

## 3. In scope for V1

- Ingest local CSV/ZIP/text files supplied by the user.
- Detect/validate source encoding and column mapping.
- Normalize to a canonical minute-bar model.
- Trade-date/calendar-date/session classification.
- Historical session schedule support.
- Data quality report.
- Parquet storage partitioned for efficient reads.
- Strategy plug-in interface.
- One-position event-driven backtest.
- Market entry/exit.
- Stop loss and take profit.
- Conservative same-bar stop/target handling.
- Configurable tick slippage.
- Configurable fees.
- Day-only, night-only, full-session modes.
- End-of-session forced exit option.
- Trade ledger and equity curve.
- Performance metrics and segmented reports.
- Reproducibility metadata.

## 4. Explicitly out of scope for V1

- Live broker connectivity.
- Order-book/Level 2 simulation.
- Tick-by-tick path reconstruction.
- Limit-order queue modeling.
- Partial fills.
- Multi-contract position scaling.
- Portfolio/multi-asset trading.
- Options.
- Margin/SPAN/VaR simulation.
- Machine learning pipeline.
- Automatic download/login from 225Labo.
- Redistribution of third-party data.

## 5. Functional requirements

### FR-01 Ingestion

The CLI can ingest one or more source files, map source columns, and write normalized Parquet without mutating source files.

### FR-02 Idempotency

Re-running ingestion with unchanged input/config produces the same normalized records and content hashes.

### FR-03 Time semantics

Every bar has an aware JST timestamp, exchange trade date, calendar date, session classification, and schedule version.

### FR-04 Data quality

The system produces a machine-readable and human-readable quality report including duplicates, missing expected minutes, tick violations, OHLC invariants, non-monotonic timestamps, and unexpected session records.

### FR-05 Backtest causality

No strategy may use future bars. A close-based signal fills no earlier than the next eligible bar.

### FR-06 Cost accounting

Gross PnL, fees, slippage and net PnL are separately visible per trade and in aggregate.

### FR-07 Reproducibility

Each run stores configuration snapshot, input dataset identifier/hash, code/version information if available, run timestamp, and strategy parameters.

## 6. Non-functional requirements

- A 5-year 1-minute dataset should be practical on a normal desktop.
- Normalized dataset load/filter should use columnar Parquet, not repeated CSV parsing.
- Core execution calculations must be deterministic.
- Error messages must identify the file/row/field involved when feasible.
- Unit tests must run without proprietary market data.
