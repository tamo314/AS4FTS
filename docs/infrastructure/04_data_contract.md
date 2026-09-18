# 04. Canonical Data Contract

## 1. Minute bar

The canonical bar schema is machine-readable in `schemas/bar_schema.yaml`.

Core columns:

| Column | Type | Required | Meaning |
|---|---|---:|---|
| `ts_jst` | datetime tz=Asia/Tokyo | yes | Actual calendar timestamp of the minute bar |
| `trade_date` | date | yes | OSE trading date |
| `calendar_date` | date | yes | Calendar date of `ts_jst` |
| `session` | enum | yes | `day` / `night` |
| `schedule_version` | string | yes | Historical session regime id |
| `instrument` | string | yes | `N225M` |
| `series_type` | enum | yes | `center_continuous` / `next_continuous` / future `contract` |
| `contract_month` | string/null | yes | null for 225Labo continuous data |
| `open` | int | yes | JPY index points |
| `high` | int | yes | JPY index points |
| `low` | int | yes | JPY index points |
| `close` | int | yes | JPY index points |
| `volume` | int/null | no | Source volume if available |
| `is_session_open` | bool | yes | bar corresponds to session opening minute/auction when identifiable |
| `is_session_close` | bool | yes | bar corresponds to session closing minute/auction when identifiable |
| `is_missing_prev_expected` | bool | yes | expected previous minute missing |
| `roll_risk` | bool | yes | conservative marker near known/estimated rollover/SQ risk |
| `is_eligible` | bool | yes | allowed for strategy processing after QC rules |
| `quality_flags` | list[str] | yes | zero or more quality codes |
| `source` | string | yes | `225labo` |
| `source_file` | string | yes | lineage |
| `source_row_number` | int | yes | lineage |

## 2. Price rules

For N225M:
- integer JPY prices
- expected tick grid: multiple of 5 JPY for ordinary exchange trading records
- high >= open and close
- low <= open and close
- high >= low

Tick violations are quality errors/warnings depending on source context; do not auto-round.

## 3. Volume

Volume is nonnegative integer when present. Zero is legal and must not be treated as missing.

## 4. Trade ledger

See `schemas/trade_schema.yaml`.

Required economic fields:
- side
- qty
- entry/exit timestamps
- signal timestamps
- raw/reference prices
- fill prices
- gross PnL
- fees
- slippage cost
- net PnL
- MAE/MFE
- holding minutes
- entry/exit reason
- strategy id/version
- parameter hash

## 5. PnL

For quantity `q` and multiplier 100:

Long:
`gross_pnl = (exit_fill - entry_fill) * 100 * q`

Short:
`gross_pnl = (entry_fill - exit_fill) * 100 * q`

`net_pnl = gross_pnl - fees - other_costs`

If slippage is already embedded in fill prices, do not subtract it a second time. `slippage_cost` is an attribution field computed relative to reference/no-slippage fills.

## 6. Data schema versioning

Use semantic-ish integer versions such as:
- `bar_schema_version: 1`
- `trade_schema_version: 1`

Breaking column/semantic changes increment the version and require migration notes.
