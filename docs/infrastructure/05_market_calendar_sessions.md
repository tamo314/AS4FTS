# 05. Market Calendar and Session Rules

## 1. Current N225M exchange specification

Current JPX specification (verified 2026-09):
- Day opening auction: 08:45
- Day regular session: 08:45–15:40
- Day closing auction: 15:45
- Night opening auction: 17:00
- Night regular session: 17:00–05:55
- Night closing auction: 06:00
- Contract unit: Nikkei 225 × 100 JPY
- Tick size: 5 JPY

## 2. Historical regimes needed for the initial 2021+ dataset

The configuration uses coarse session boundaries plus auction metadata.

### Regime A — through 2021-09-20

- Day session overall: 08:45–15:15
- Night session overall: 16:30–05:30

Relevant history: the 2016 J-GATE renewal moved index futures day opening to 08:45 and extended night close to 05:30.

### Regime B — 2021-09-21 through 2024-11-04

- Day session overall: 08:45–15:15
- Night session overall: 16:30–06:00

On 2021-09-21 J-GATE3.0 extended the night session to 06:00.

### Regime C — from 2024-11-05

- Day session overall: 08:45–15:45
- Night session overall: 17:00–06:00
- Day regular session ends 15:40; closing auction 15:45
- Night regular session ends 05:55; closing auction 06:00

JPX changed derivatives trading hours in conjunction with the cash market extension on 2024-11-05.

## 3. Important implementation note

The ranges above describe exchange session boundaries, not a promise that every minute has an OHLC record. Auctions, no-trade minutes, interruptions and source conventions can create gaps.

Do not pre-generate bars and fill them. Instead, generate an expected-session minute grid for quality analysis and compare source bars against it.

## 4. Trade date model

`trade_date` is the exchange trading date that groups the preceding evening/night session and the day session according to OSE rules.

For 225Labo, the source states the night-session date follows the OSE convention and uses the next business/trading date. Therefore actual timestamps must be reconstructed using an exchange calendar relation.

## 5. Exchange calendar table

Implement a persisted table with at least:

| field | meaning |
|---|---|
| `trade_date` | OSE trading date |
| `previous_trade_date` | prior OSE trading date |
| `next_trade_date` | next OSE trading date |
| `night_calendar_start_date` | actual date on which evening night session starts |
| `is_holiday_trading_day` | whether a holiday trading session exists |
| `schedule_version` | regime id |

The system should allow an explicit CSV/YAML calendar override supplied by the user.

At a regime boundary, day-session rules are selected by `trade_date`, whereas
night-session rules are selected by `night_calendar_start_date`. This preserves
the actual schedule of a session that starts before a rules change and ends on
its first trade date after that change.

## 6. Holiday trading

OSE derivatives holiday trading began in 2022. Holiday sessions may affect the relationship between Japanese public holidays, calendar days, and trade dates. Do not use a generic Japanese bank-holiday calendar as a substitute for the exchange calendar.

If the calendar is incomplete, classify the uncertainty as a quality/error condition rather than guessing.

## 7. Forced-flat configuration

Entry/force-exit times are strategy/backtest policy, not exchange rules. Store them separately in `backtest.yaml` and validate them against the effective session schedule.
