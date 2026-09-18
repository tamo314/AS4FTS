# 02. Architecture

## 1. Data flow

```text
User-owned source files
        |
        v
 data/raw/225labo/              immutable
        |
        v
 Ingest Adapter
  - decode
  - source mapping
  - provenance
        |
        v
 Bronze
  source-shaped parsed records
        |
        v
 Normalizer + Calendar Classifier
        |
        v
 Silver canonical minute bars
        |
        +--> Quality checks/reports
        |
        v
 Gold backtest dataset
        |
        v
 Feature pipeline
        |
        v
 Strategy --> Signal/Intent
        |
        v
 Execution Engine
        |
        +--> Slippage / Fees / Risk gates
        |
        v
 Portfolio state / Trade ledger
        |
        v
 Metrics + Reports
```

## 2. Python modules

```text
src/n225m_bt/
  __init__.py
  cli.py
  config.py
  domain.py

  ingest/
    base.py
    source_detect.py
    labo225.py

  normalize/
    bars.py
    timestamps.py

  calendar/
    model.py
    session_rules.py
    classifier.py

  quality/
    checks.py
    report.py

  io/
    parquet.py
    manifest.py

  features/
    base.py
    returns.py

  strategies/
    base.py
    examples.py

  backtest/
    engine.py
    execution.py
    orders.py
    portfolio.py
    costs.py
    intrabar.py

  reports/
    metrics.py
    segmentation.py
    writer.py
```

## 3. Interfaces

### DataSourceAdapter

Responsibilities:
- discover candidate files
- decode source
- resolve/match source columns
- emit typed source records
- attach provenance (`source_file`, `source_row`, source hash)

Must NOT:
- invent missing prices
- silently change dates
- assign fabricated contract months

### CalendarClassifier

Input: timestamp/date/time and configured session regimes.

Output:
- actual `ts_jst`
- `calendar_date`
- `trade_date`
- `session`
- `schedule_version`
- session open/close flags where determinable

### Strategy

Input: historical information available up to current bar only.

Output: intent/signal, not a fill.

Recommended minimal interface:

```python
class Strategy(Protocol):
    def on_bar(self, ctx: StrategyContext, bar: Bar) -> Signal | None: ...
```

### ExecutionModel

Input:
- pending order
- current bar
- instrument spec
- slippage/cost config

Output:
- fill or no fill

### Portfolio

Owns position state and realized/unrealized accounting. It must not compute technical indicators.

## 4. Layer boundaries

- Source parsing knows source quirks but not trading logic.
- Calendar logic knows exchange schedules but not strategy logic.
- Strategy knows market history but not file formats.
- Execution knows orders/fills but not indicator formulas.
- Reports consume ledgers/results but must not change PnL.

## 5. Storage layout

Suggested:

```text
data/
  raw/225labo/center/YYYY/
  raw/225labo/next/YYYY/
  bronze/source=225labo/series=center/year=YYYY/*.parquet
  silver/instrument=N225M/series=center/year=YYYY/month=MM/*.parquet
  gold/instrument=N225M/series=center/year=YYYY/month=MM/*.parquet

results/<run_id>/
  run_manifest.json
  config_snapshot/
  trades.parquet
  equity.parquet
  metrics.json
  metrics.md
  quality_summary.json
```

## 6. Dataset identity

Generate a dataset manifest containing:
- normalized schema version
- source file hashes
- source adapter version
- normalization config hash
- earliest/latest timestamps
- row count
- quality summary

Use a stable hash over canonical manifest content as `dataset_id`.
