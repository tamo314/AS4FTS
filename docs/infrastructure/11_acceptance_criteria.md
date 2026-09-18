# 11. Acceptance Criteria

## A. Project quality

- [ ] `pytest` passes from clean checkout without proprietary data.
- [ ] `ruff check .` passes.
- [ ] formatter check passes.
- [ ] `mypy` passes at the agreed strictness level.
- [ ] CLI help works.

## B. Configuration

- [ ] All provided YAML examples validate.
- [ ] Unknown critical keys are rejected or warned clearly.
- [ ] Invalid tick size/multiplier fails fast.
- [ ] Overlapping session effective ranges fail fast.

## C. Calendar/session

- [ ] 2021-09-20 uses regime A.
- [ ] 2021-09-21 uses regime B.
- [ ] 2024-11-04 uses regime B.
- [ ] 2024-11-05 uses regime C.
- [ ] JST timezone is retained.
- [ ] Day/night session classification is correct at boundaries.
- [ ] Trade-date/calendar-date distinction is tested with an evening night-session bar.

## D. Ingestion

- [ ] UTF-8 and CP932 synthetic fixtures ingest.
- [ ] Explicit source mapping works.
- [ ] Auto-detection reports mapping before normalization.
- [ ] Missing required price column fails with actionable error.
- [ ] Source SHA-256 and row lineage are persisted.
- [ ] Raw file bytes are unchanged after ingestion.

## E. Data quality

- [ ] Duplicate conflicting timestamp detected.
- [ ] Impossible OHLC detected.
- [ ] 5-yen tick violation detected, not rounded.
- [ ] Missing expected minute detected.
- [ ] Statistical price jump is flagged/reported but not automatically deleted.
- [ ] Fatal quality issue prevents Gold generation in strict mode.

## F. Backtest causality

- [ ] Close-of-t signal never fills before next eligible bar.
- [ ] Buy slippage worsens price upward.
- [ ] Sell slippage worsens price downward.
- [ ] 1 tick equals 5 price points and 500 JPY/contract economic value.
- [ ] Long/short PnL formulas pass exact integer examples.
- [ ] Stop/target same-bar ambiguity uses conservative outcome by default.
- [ ] Gap-through stop does not fill optimistically at unreachable stop price.
- [ ] No pyramiding in V1.
- [ ] Forced-flat behavior respects historical session close.

## G. Output/reproducibility

- [ ] Every run writes run manifest.
- [ ] Every completed trade has gross, fees, slippage attribution, net PnL.
- [ ] Re-running same deterministic case produces byte-equivalent or semantically equivalent ledgers.
- [ ] Dataset manifest contains source hashes and schema version.
- [ ] No 225Labo actual data is present in repository artifacts.

## H. Performance

- [ ] Synthetic/representative multi-million-row Parquet scan is feasible on a normal workstation without reading the entire raw CSV repeatedly.
- [ ] Backtest does not perform pathological per-row DataFrame concatenation.
