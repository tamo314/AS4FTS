# 09. CLI and Outputs

## 1. Proposed CLI

Command name: `n225m-bt`

### Validate config

```bash
n225m-bt config validate --config-dir config/
```

### Inspect source

```bash
n225m-bt data inspect data/raw/225labo/center/2025/file.csv
```

Outputs detected encoding, delimiter, candidate headers, candidate mapping and sample metadata without redistributing the data.

### Ingest

```bash
n225m-bt data ingest \
  --source 225labo \
  --series center \
  --input data/raw/225labo/center/ \
  --config config/data.yaml
```

### Quality check

```bash
n225m-bt data quality --dataset <dataset_id>
```

### Backtest

```bash
n225m-bt backtest run \
  --dataset <dataset_id> \
  --strategy example_breakout \
  --config config/backtest.yaml
```

### Batch slippage

```bash
n225m-bt backtest sweep \
  --dataset <dataset_id> \
  --strategy example_breakout \
  --slippage-ticks 0,1,2,3
```

### Report

```bash
n225m-bt report build --run <run_id>
```

## 2. Run output

```text
results/<run_id>/
  run_manifest.json
  config_snapshot/
  trades.parquet
  orders.parquet
  fills.parquet
  equity.parquet
  metrics.json
  metrics.md
  segment_metrics.parquet
```

## 3. Run manifest

Include:
- `run_id`
- `created_at_jst`
- dataset id
- dataset schema version
- strategy name/version
- parameter JSON + hash
- backtest config hash
- instrument config hash
- session config hash
- source code git commit if available
- Python/package versions
- random seed if any

## 4. Exit codes

- 0 success
- nonzero on invalid config, fatal data quality, failed ingestion, or backtest invariant failure

CLI must not hide exceptions without an actionable summary.
