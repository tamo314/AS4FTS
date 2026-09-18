# Required Specification Test Scenarios

These scenarios should become executable pytest tests with synthetic data.

## T01 Tick economics

Given N225M tick size 5 and multiplier 100:
- Long entry 40000, exit 40005, qty=1 -> gross +500 JPY.
- Short entry 40000, exit 39995 -> gross +500 JPY.

## T02 Adverse slippage

Reference open 40000, slippage 1 tick:
- buy fill = 40005
- sell fill = 39995

## T03 No look-ahead

Bar 09:31 close generates LONG. Bar 09:31 open/close may not be used as the entry fill. Earliest default fill is next eligible observed bar open.

## T04 Missing minute

Bars at 10:00 and 10:02 inside an expected continuous session:
- detect missing 10:01
- do not create a synthetic OHLC bar
- a pending next-bar order after 10:00 may fill at 10:02 if within max delay, and the delay must be recorded.

## T05 Conservative simultaneous stop/target (long)

Entry 40000, stop 39950, target 40100.
Next bar high 40120, low 39940.
Expected default exit: stop-side/adverse outcome, not target.

## T06 Conservative simultaneous stop/target (short)

Entry short 40000, stop 40050, target 39900.
Next bar high 40060, low 39880.
Expected default exit: stop-side/adverse outcome.

## T07 Gap-through stop

Long stop 39950, next eligible bar open 39920.
Expected stop-market reference/fill starts from 39920 (then adverse slippage), not 39950.

## T08 Regime boundary 2021

- 2021-09-20 -> old night close 05:30 regime.
- 2021-09-21 -> night close 06:00 regime.

## T09 Regime boundary 2024

- 2024-11-04 -> day close 15:15, night open 16:30.
- 2024-11-05 -> day close 15:45, night open 17:00.

## T10 Evening night bar trade date

Synthetic source record:
- source trade_date = a Monday
- time = 17:30 or regime-equivalent evening start
Calendar mapping indicates the evening session actually began on previous eligible calendar/trading session date.
Expected:
- `trade_date` remains Monday
- `calendar_date` and `ts_jst` use the actual evening calendar date.

Do not implement this with unconditional `trade_date - 1 day`.

## T11 Duplicate conflict

Two rows same `(instrument, series_type, ts_jst)` with different close prices -> quality ERROR/FATAL.

## T12 Tick violation

Price 40003 -> quality flag `TICK_GRID_VIOLATION`; do not round to 40005.

## T13 OHLC invariant

Open 40000, high 39990 -> error.

## T14 Raw immutability

Hash raw fixture before and after ingest; hashes equal.

## T15 Deterministic rerun

Same synthetic dataset/config run twice -> identical trade economic fields and aggregate metrics.

## T16 Forced flat by relative close

With `force_flat_minutes_before_session_close=5`:
- regime B day session close 15:15 -> forced-flat policy based on 15:10 boundary
- regime C day session close 15:45 -> based on 15:40 boundary

Exact event behavior at the cutoff must be documented/tested.

## T17 No cross-session pending order

A signal near session end with no next eligible bar before close must be canceled when `allow_cross_session_pending_order=false`.

## T18 Fees and no double-counted slippage

Gross PnL must be computed from actual slipped fill prices. `slippage_cost_jpy` is attribution only and must not be subtracted again from net PnL unless the accounting model explicitly defines otherwise.
