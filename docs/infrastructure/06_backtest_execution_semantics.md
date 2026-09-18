# 06. Backtest and Execution Semantics

## 1. Event ordering per bar

For each eligible bar, use a deterministic ordering. Recommended V1:

1. Apply pending next-bar market orders at current bar open.
2. Update position with entry fill.
3. Evaluate existing protective stop/target against the bar range.
4. Resolve simultaneous stop/target using configured intrabar policy.
5. Process forced-exit rules if applicable.
6. Update indicators/features using information available through this bar.
7. Call strategy at bar close.
8. Convert new signal into pending order for the next eligible bar.
9. Persist events/diagnostics.

A newly generated close signal cannot fill at that same bar's open or close under the default V1 model.

## 2. Market order fill

Default:
- reference fill = next eligible bar open
- fill = reference price + adverse tick slippage

For `slippage_ticks = s`, tick size `T=5`:
- Buy fill = reference + `s*T`
- Sell fill = reference - `s*T`

This applies to both entries and exits in the adverse direction.

## 3. Stop and take-profit

Protective levels are specified in absolute price or ticks/points from actual entry fill.

For a long position:
- stop is touched if `bar.low <= stop_price`
- target is touched if `bar.high >= target_price`

For a short position:
- stop is touched if `bar.high >= stop_price`
- target is touched if `bar.low <= target_price`

## 4. Same-bar ambiguity

If both stop and target are touched inside the same minute and no tick path is known:

Default `intrabar_policy=conservative`:
- choose the economically adverse exit for the current position.

Other policies can exist for sensitivity analysis but must be explicit and labeled. Never silently choose profit-first.

## 5. Gap-through stop

For a long stop below market, if next bar opens below the stop, fill at the worse of:
- bar open adjusted for slippage, or
- policy-specific stop execution rule.

Recommended V1: stop-market behavior, so gap-through fills at bar open plus adverse slippage, not magically at the stop price.

Analogous rule for shorts.

## 6. Missing next bar

A pending next-bar order executes on the next **eligible observed bar**, not a synthesized minute. Record the delay/gap. Optionally reject if gap exceeds configured maximum minutes.

## 7. Session boundaries

Default modes:
- `day_only`
- `night_only`
- `full_session`

For a day-only strategy, pending orders must not carry into the night unless explicitly allowed.

Forced flat is configurable by minutes before session close rather than one hardcoded clock time, so it survives historical schedule changes.

Example:
- `new_entry_cutoff_minutes_before_close: 15`
- `force_flat_minutes_before_close: 5`

## 8. Position model

V1 states:
- `FLAT`
- `LONG 1`
- `SHORT 1`

No simultaneous long/short, no pyramiding.

If an opposite signal arrives while in a position, policy must be explicit:
- default: `close_then_reverse_next_bar=false`; close current position first, no same-bar instant reversal.

## 9. Fees

Fees are configured per contract per side or round trip. Store exact model in run manifest.

Default example config can be zero because broker fees vary, but production research should set realistic fees.

## 10. Slippage stress test

The reporting pipeline must support batch runs with at least:
- 0 ticks
- 1 tick
- 2 ticks
- 3 ticks

Metrics should show robustness to friction.

## 11. MAE/MFE

For each trade, calculate maximum adverse/favorable excursion from actual entry fill using observed OHLC during holding period. Document whether entry/exit bars are included; V1 includes them after the fill event while respecting event ordering.

## 12. Determinism

Same input dataset + same config + same code must yield same trade ledger ordering and PnL.
