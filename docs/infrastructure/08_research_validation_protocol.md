# 08. Research and Validation Protocol

## 1. Goal

Prevent strategy selection from becoming an exercise in fitting the full historical sample.

## 2. Recommended initial split

For data available through 2026, a practical first split is:

- 2021–2023: development / exploratory research
- 2024: validation / parameter selection
- 2025: primary out-of-sample
- 2026: final confirmation / forward-like holdout

Do not change a strategy using information from a holdout and then continue calling that period out-of-sample.

## 3. Walk-forward

After a strategy is specified, support rolling evaluation such as:
- train/lookback: 12 months
- test: 3 months
- step: 3 months

The framework should store each fold separately and aggregate only after individual results are available.

## 4. Minimum robustness views

Report:
- by calendar year
- by month
- by weekday
- by session
- by hour / time bucket
- normal vs SQ/roll-risk periods where flags exist
- slippage stress 0–3 ticks

## 5. Minimum metrics

- net profit
- gross profit/loss
- trade count
- win rate
- average win/loss
- payoff ratio
- profit factor
- expectancy per trade
- max drawdown
- return/drawdown ratio
- MAE/MFE distribution
- holding duration
- exposure/time in market
- consecutive wins/losses

Sharpe-like statistics may be included but should not be the sole criterion for high-frequency intraday trades.

## 6. Strategy acceptance concept

Do not encode one universal threshold as truth. However, a candidate intended for further work should generally:
- retain positive expectancy after realistic friction
- not depend on one year or one narrow time bucket
- have sufficient trade count for its claimed behavior
- show stable performance under nearby parameter values
- survive at least 1–2 ticks of slippage stress if turnover is high

## 7. Multiple testing

Store every parameter sweep configuration and result. Avoid presenting only the best run. Future extension may add deflated Sharpe/probability-of-backtest-overfitting analysis.

## 8. Final contract-specific validation

Before considering live trading, re-test using contract-specific data (e.g. JPX or another licensed source) because the initial 225Labo center series is a continuous research series and may not reproduce actual roll/contract execution exactly.
