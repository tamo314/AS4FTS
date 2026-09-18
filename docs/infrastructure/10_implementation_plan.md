# 10. Implementation Plan

Implement phases in order. Do not jump to strategy optimization before data/time semantics are tested.

## Phase 0 — Project skeleton

Deliver:
- `pyproject.toml`
- package layout
- CLI entry point
- typed config loader
- lint/test/type-check commands

Tests:
- load provided YAML configs
- reject malformed configs

## Phase 1 — Domain model and calendar/session engine

Deliver:
- enums/domain dataclasses or Pydantic models
- instrument spec
- versioned schedule rules
- session classifier
- trade/calendar date model

Tests:
- regime boundaries around 2021-09-21 and 2024-11-05
- day/night classification
- timestamp awareness
- invalid time detection

Do not yet ingest real proprietary data.

## Phase 2 — Source inspection and 225Labo adapter

Deliver:
- file hashing
- encoding/delimiter/header detection
- explicit/auto column mapping
- Bronze writer
- source lineage

Tests use synthetic CSV fixtures in CP932 and UTF-8.

## Phase 3 — Silver normalization and quality pipeline

Deliver:
- canonical bar schema
- timestamp reconstruction
- session/trade-date metadata
- Parquet output
- expected-minute grid
- quality checks/reports
- dataset manifest/id

Integration test: synthetic source -> Silver -> QC.

## Phase 4 — Gold dataset

Deliver:
- eligibility flag
- session minute indices
- minimal derived fields
- partition filtering

Avoid strategy-specific indicators here.

## Phase 5 — Backtest engine core

Deliver:
- order/fill models
- portfolio state
- next-bar market fills
- stop/target
- conservative intrabar resolution
- gap-through stop behavior
- slippage
- fees
- forced flat
- day/night/full modes

Regression tests for every economic rule.

## Phase 6 — Strategy API and baseline strategies

Deliver at least two trivial test strategies, not alpha claims:
- `AlwaysFlatStrategy`
- deterministic synthetic-test strategy (e.g. enter on configured timestamp)

Optional demonstration indicator strategy may be included but must be labeled example only.

## Phase 7 — Ledger, metrics, reports

Deliver:
- orders/fills/trades/equity Parquet
- metrics JSON/Markdown
- segmented stats
- slippage sweep

## Phase 8 — Reproducibility and hardening

Deliver:
- run manifest hashes
- idempotency checks
- logging
- performance sanity benchmark
- end-to-end CLI test
- documentation synchronization

## Phase 9 — User real-data onboarding

Once user places actual 225Labo files locally:
- run `data inspect`
- capture resolved source mapping in local config
- ingest one year first
- inspect quality report
- then ingest full history

Never add real downloaded files to Git.
