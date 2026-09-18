# 12. Sources, Verified Facts, and Assumptions

Last reviewed: 2026-09-13 JST.

## Primary sources

### JPX — Nikkei 225 mini contract specification

https://www.jpx.co.jp/derivatives/products/domestic/225mini/01.html

Verified current facts:
- day opening 08:45
- regular session through 15:40, closing auction 15:45
- night opening 17:00
- regular session through 05:55, closing auction 06:00
- contract unit Nikkei 225 × 100 JPY
- tick size 5 JPY

### JPX — trading hours

https://www.jpx.co.jp/derivatives/rules/trading-hours/index.html

Used for current auction/session detail.

### JPX — J-GATE3.0 launch, 2021-09-21

https://www.jpx.co.jp/corporate/news/news-releases/0060/20210921-01.html

Verified: night session was extended to 06:00 on 2021-09-21.

### JPX — 2016 J-GATE history

https://www.jpx.co.jp/news/0060/20170719-01.html

Verified: on the 2016 J-GATE renewal, index futures day opening moved from 09:00 to 08:45 and night session close extended to 05:30. This supports the pre-2021 schedule used for the initial 2021 history.

### JPX — 2024-11-05 trading-hours changes

https://www.jpx.co.jp/english/corporate/news/news-releases/1030/20241103-01.html

Verified: derivatives trading hours changed on 2024-11-05 in conjunction with the cash-market trading-hours extension.

### 225Labo — Nikkei 225 mini data page

https://225labo.com/modules/downloads_data/index.php?cid=3

Verified:
- minute data available from 2006
- 1, 3, 5, 10, 15, 20, 30, 60-minute intervals
- from 2011-02-14 the provided center series is a continuous series using the same contract month as the large Nikkei 225 futures center/near contract concept described by 225Labo
- registered members may download data for free
- redistribution/third-party provision is prohibited by the site terms shown on the page

### 225Labo — example center-series explanation

https://225labo.com/modules/downloads_data/index.php?cid=3&lid=115&page=singlefile

Verified:
- the mini center series can differ from simple nearest-month mini because it follows the contract month corresponding to the most-active/large-futures center convention described by 225Labo
- night-session dates follow the Osaka Exchange date convention and are shown as the next business/trading date

## Assumptions requiring validation when actual files are available

1. Exact 225Labo CSV column names/order/encoding are not frozen in this package.
2. Availability/meaning of volume in each downloadable file must be inspected.
3. Whether source bar timestamps label bar start, bar end, or auction minute must be verified from actual files/site documentation before relying on minute-level boundary semantics.
4. Exact exchange holiday-trading calendar should be supplied/generated from authoritative JPX data for full historical reconstruction.
5. A center-series rollover marker is not assumed to exist in source data. `roll_risk` may initially be generated conservatively from SQ/calendar rules or left false/unknown until validated.

## Design response to uncertainty

The adapter and calendar components must expose uncertainty rather than silently guess. Actual source inspection is an onboarding step after code is implemented.
