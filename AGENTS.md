# AGENTS.md

## Mission

Implement a reproducible research-grade intraday backtesting platform for Nikkei 225 mini futures (N225M) using 1-minute bars. Initial market data source is user-provided 225Labo continuous center-contract data. Architecture must allow later replacement with contract-specific JPX data without rewriting strategies.

## Mandatory reading order

Before coding, read:

1. `DECISIONS.md`
2. `docs/infrastructure/01_scope_requirements.md`
3. `docs/infrastructure/02_architecture.md`
4. `docs/infrastructure/04_data_contract.md`
5. `docs/infrastructure/05_market_calendar_sessions.md`
6. `docs/infrastructure/06_backtest_execution_semantics.md`
7. `docs/infrastructure/07_quality_validation.md`
8. `docs/infrastructure/10_implementation_plan.md`
9. `docs/infrastructure/11_acceptance_criteria.md`

## Non-negotiable rules

1. Never modify files under `data/raw/`.
2. Never commit or redistribute 225Labo data.
3. Do not make the backtester read raw CSV directly.
4. All normalized timestamps must be timezone-aware `Asia/Tokyo`.
5. Keep `calendar_date` and `trade_date` as separate concepts.
6. Historical session rules are configuration-driven and date-versioned.
7. Do not infer an exact futures contract code from 225Labo center-series data.
8. Mark `contract_month` nullable for continuous data.
9. No look-ahead: a signal using bar `t` close cannot fill before bar `t+1`.
10. Default market fill is next eligible bar open plus adverse slippage.
11. Long buy fills slip upward; long sell/exit fills slip downward. Reverse for shorts.
12. If stop and take-profit are both reachable inside one minute and ordering is unknown, use conservative adverse ordering by default.
13. Costs must be explicit: `gross_pnl`, `fees`, `slippage_cost`, `net_pnl`.
14. V1 position size is one contract, max one open position, no pyramiding, no averaging down.
15. Backtest results must be deterministic given identical input, config, and code version.
16. Every bug fix that changes PnL semantics requires a regression test.
17. No silent forward-fill of missing OHLC bars.
18. Data-quality failures must be surfaced in a report; severe failures may abort processing.
19. Strategy code must not contain broker/exchange adapter logic.
20. Execution engine must not contain strategy-specific indicator logic.

## Technology constraints

- Python: `>=3.12,<3.14`
- Prefer Polars for tabular transforms and Parquet IO.
- Use PyArrow-backed Parquet where applicable.
- Pydantic v2 for typed configuration/domain validation.
- PyYAML for YAML configuration loading.
- Typer for CLI.
- pytest for tests.
- Ruff for lint/format.
- mypy with reasonably strict settings.
- Standard library `zoneinfo` for `Asia/Tokyo`.

Do not add heavy dependencies unless justified in an ADR or code comment.

## Coding style

- Type annotations on public functions/classes.
- Small pure functions for time/session classification and PnL calculations.
- Domain types/enums for `Session`, `Side`, `OrderType`, `ExitReason`, `SeriesType`.
- Decimal is not required for N225M prices because tick size is an integer 5 JPY; store prices as integer JPY.
- Quantity is integer contracts.
- Monetary PnL is integer JPY wherever possible.
- Avoid hidden global state.
- Configuration must be injectable in tests.

## Expected package structure

```text
src/n225m_bt/
  cli.py
  config.py
  domain.py
  ingest/
  normalize/
  calendar/
  quality/
  features/
  strategies/
  backtest/
  reports/
  io/
```

## Testing policy

- Unit tests for pure calculations.
- Golden/regression tests for execution semantics.
- Property/invariant tests where practical.
- Integration test from synthetic raw CSV fixture -> Parquet -> backtest -> report.
- Real 225Labo data must NOT be committed as a fixture.
- Synthetic fixtures must include night session, missing minute, regime boundary, simultaneous stop/target case, and roll-risk marker.

## Git/implementation behavior

- Work phase-by-phase according to `docs/infrastructure/10_implementation_plan.md`.
- Keep each phase independently testable.
- Run tests/lint after each material change.
- Do not change documented semantics merely to make tests pass.
- If source CSV layout is unknown, implement adapter discovery/configuration and fail with a useful message; do not invent an undocumented fixed column order.

## Definition of done

A phase is complete only when its acceptance checks in `docs/infrastructure/11_acceptance_criteria.md` pass and documentation/config examples are synchronized with code.
