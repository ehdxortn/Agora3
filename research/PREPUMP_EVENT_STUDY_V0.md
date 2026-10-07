# PRE-PUMP EVENT STUDY V0 — PREREGISTRATION

## Mission
Research-only screening for a private discretionary trading copilot.
The goal is to surface liquid Upbit-tradable assets BEFORE rapid upward expansion.
No live orders, no production deployment, no APEX modification.

## Universe
Development universe is intentionally limited to the six dual-observed assets already present in the research database:
ARB, ENA, NEAR, ONDO, POL, SUI.

This V0 study is a mechanism screen, not the final universe selector.

## Clock and causality
Primary screening clock: completed 1h bars because aligned Upbit/Binance 1h history is already available through 2026-10-07.
At decision time t, every feature must use data at or before the completed bar t.
Future bars may be used ONLY to form outcome labels.

Later work will refine surviving mechanisms on 15m data.

## Windows
- Development/train: 2026-01-01 through 2026-06-30 UTC.
- Validation: 2026-07-01 through 2026-09-30 UTC.
- October 2026 is NOT used to tune V0. It remains a small shadow period.

## Event labels
For a completed Upbit 1h bar at t:

PUMP_1H:
- max Upbit high in t+1 >= close_t * 1.03.

PUMP_4H:
- max Upbit high in t+1..t+4 >= close_t * 1.05.

EARLY_PUMP_4H:
- PUMP_4H is true;
- the asset has NOT already risen >= 3% in the trailing 4 completed hours at t.

The primary V0 target is EARLY_PUMP_4H.
Thresholds are frozen for this screening round and are not to be rescued after seeing validation.

## Causal feature families
All are computed at t from completed data only.

1. Price state
- ret_1h
- ret_3h
- ret_6h
- ret_24h
- distance to prior 24h high
- distance to prior 24h low
- trailing 6h max drawdown / rebound state

2. Compression / expansion
- 6h realized absolute-return sum
- 24h realized absolute-return sum
- compression_ratio = 6h / scaled 24h
- current true-range proxy relative to trailing median

3. Activity
- Upbit trade_value_krw ratio to trailing 24h median
- Upbit trade_value acceleration vs prior 6h
- Binance quote_volume ratio to trailing 24h median
- Binance quote_volume acceleration vs prior 6h

4. Cross-exchange state
- Binance ret_1h minus Upbit ret_1h
- Binance ret_3h minus Upbit ret_3h
- normalized Upbit/Binance price-ratio deviation from its trailing 24h median

5. BTC context
- latest fully completed BTC 4h regime available at t
- BTC 4h impulse / direction

## First-pass tests
This study is not a parameter search.

For each feature:
- split development observations into quintiles using development-only cut points;
- measure EARLY_PUMP_4H event rate in each quintile;
- compute top-quintile lift vs unconditional event rate;
- report same frozen cut points on validation.

Also test a simple non-fitted score:
- +1 if Upbit activity ratio is in development top quintile
- +1 if Binance activity ratio is in development top quintile
- +1 if 6h compression ratio is in development bottom quintile
- +1 if Binance-minus-Upbit 1h return spread is in development top quintile
- +1 if price is within the upper half of the prior 24h range without trailing-4h return >=3%

No weights may be optimized in V0.

## Primary evidence metrics
- base event rate
- event rate by feature quintile
- lift vs base
- precision@top 5% score observations
- recall of EARLY_PUMP_4H events captured in top 5%
- median future 4h MFE
- median future 4h MAE
- MAE-before-MFE diagnostic when possible
- results by symbol
- results by BTC regime
- development vs validation stability

## Interpretation
PASS_SCREEN:
- at least one causal feature family has validation top-quintile lift >= 1.5x;
- same feature direction agrees with development;
- validation sample contains >= 30 EARLY_PUMP_4H events overall.

PROMISING_SCORE:
- frozen simple score top 5% has validation precision lift >= 1.75x over base;
- signal is not dominated by one asset (>50% of selected observations);
- at least 4 of 6 assets show non-negative lift.

Anything else is WEAK/REJECT for V0.
A failure rejects only the tested feature construction/thresholds, not the entire pre-pump mission.

## Anti-leakage
- no future high/close/volume/orderbook values in features;
- rolling statistics are shifted so they use t and prior only as explicitly defined;
- labels never become features;
- no validation-driven threshold change;
- no October tuning.

## Next step after V0
If a family survives:
- rebuild it on 15m;
- add exact lead-time measurement;
- add realistic spread/slippage;
- add order-book/taker/OI features prospectively;
- shadow-rank candidates before any real-money reliance.
