# 03. Data Pipeline

## 1. Raw layer

Raw files are user-owned and immutable.

Required behavior:
- never rewrite encoding
- never rename/move automatically unless explicitly copying into a managed raw directory
- calculate SHA-256
- record file size and modified time

225Labo data must not be committed to Git.

## 2. Source format discovery

Because the exact downloadable CSV layout can change or be unavailable before login, the adapter must support:

1. encoding candidates: UTF-8/UTF-8-SIG, CP932/Shift-JIS
2. delimiter detection: comma/tab where reasonable
3. header detection
4. configurable explicit mapping
5. candidate column matching by normalized Japanese/English names

Canonical required concepts:
- source date or datetime
- source time if separate
- open
- high
- low
- close
- volume if supplied

If volume is absent, store nullable volume and explicitly record `volume_available=false` in the dataset manifest. Do not synthesize it.

## 3. Source mapping configuration

Support a mapping block such as:

```yaml
source_mapping:
  date: "日付"
  time: "時間"
  open: "始値"
  high: "高値"
  low: "安値"
  close: "終値"
  volume: "出来高"
```

`auto` mode may propose a mapping, but the resolved mapping must be written into the ingestion manifest.

## 4. Timestamp normalization

225Labo states that night-session records use the Osaka Exchange trading-date convention (night session associated with the next exchange business date). Therefore source `date` may be a trade date rather than the actual calendar date for evening bars.

Normalization algorithm must not merely parse `source_date + source_time` as actual timestamp.

Recommended process:

1. Parse `source_date` as candidate `trade_date` for source records.
2. Parse source time.
3. Classify time into day/night according to the historical schedule effective for that trade date.
4. For day-session records, `calendar_date = trade_date`.
5. For night-session evening portion (e.g. 16:30/17:00 through 23:59), map `calendar_date` to the actual prior calendar session date using exchange calendar relationships, not simply `trade_date - 1 day`.
6. For after-midnight portion, calendar date generally equals trade date calendar date, subject to exchange trading-date rules.
7. Preserve original source fields in Bronze for audit.

The implementation must support weekends, exchange holidays and holiday trading. A robust solution uses a generated/maintained exchange trading calendar table rather than arithmetic subtraction.

## 5. Bronze schema

Bronze preserves source semantics:
- `source_file`
- `source_sha256`
- `source_row_number`
- raw source date/time strings
- parsed numeric OHLCV
- resolved mapping version
- parse warnings

## 6. Silver normalization

Silver conforms to `schemas/bar_schema.yaml`.

Required operations:
- integer price conversion
- timezone-aware timestamp
- trade/calendar dates
- session/schedule version
- source lineage
- quality flags
- sorted unique natural key validation

Recommended natural key for continuous 225Labo data:

`(instrument, series_type, ts_jst)`

Duplicates are errors unless a documented source rule resolves them.

## 7. Gold preparation

Gold may add:
- session minute index
- previous close
- simple returns
- gap from previous eligible bar
- SQ/roll-risk flags if available/configured
- eligibility flags for strategy entry

Gold must not remove bad data without recording why. Prefer `is_eligible` and quality flags.

## 8. Partitioning

Partition Silver/Gold by year/month. Avoid excessively small partitions.

Example:

```text
year=2025/month=01/part-000.parquet
```

## 9. Incremental processing

Ingestion should skip unchanged files by hash. A changed source file invalidates dependent normalized partitions and dataset manifest.
