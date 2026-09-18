# 07. Data Quality and Validation

## 1. Quality philosophy

Do not silently repair market data. Detect, classify, report, and only exclude according to explicit policy.

## 2. Required checks

### Structural
- file readable
- required columns resolvable
- numeric parse success
- timestamps parseable
- timestamps monotonic after sort
- duplicate natural keys

### OHLC
- `high >= open`
- `high >= close`
- `low <= open`
- `low <= close`
- `high >= low`
- prices positive
- expected 5-JPY grid for N225M

### Volume
- null allowed if source lacks volume
- otherwise integer and >=0

### Session/calendar
- bar timestamp belongs to a configured session
- trade date mapping is possible
- schedule version resolved
- no unexplained bars inside known exchange breaks

### Continuity
- missing expected minutes
- unusually long gaps inside a session
- duplicated minutes
- jump/outlier diagnostics

## 3. Severity

Suggested codes:
- INFO
- WARN
- ERROR
- FATAL

Examples:
- missing low-activity minute: WARN
- duplicate timestamp with conflicting prices: ERROR/FATAL
- impossible OHLC: ERROR
- unresolvable timestamp/trade date: FATAL

## 4. Quality flags on bars

Use stable codes, e.g.:
- `TICK_GRID_VIOLATION`
- `OHLC_INVARIANT`
- `MISSING_PREV_EXPECTED`
- `UNEXPECTED_SESSION_TIME`
- `DUPLICATE_TIMESTAMP`
- `SOURCE_PARSE_WARNING`
- `CALENDAR_UNCERTAIN`
- `ROLL_RISK`

## 5. Outliers

Large returns are not automatically bad data. Flag statistical outliers for review but do not drop them automatically.

## 6. Quality report outputs

For every ingest build:
- `quality_summary.json`
- `quality_issues.parquet`
- `quality_report.md`

Include counts by year/month/session/flag and sample lineage references.

## 7. Gate to backtesting

Gold dataset generation should fail if FATAL issues exist.

For ERROR issues, behavior is configurable:
- strict: fail
- permissive: mark `is_eligible=false` and proceed with explicit warning

Default: strict.
