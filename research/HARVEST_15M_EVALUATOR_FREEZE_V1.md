# HARVEST 15M Evaluator Freeze v1

Status: FROZEN BEFORE PRIMARY VALIDATION OUTCOME QUERY
Date: 2026-09-19 KST
Branch: `research/harvest-15m-v1`
Parent contract: `HARVEST_15M_REGIME_ASSET_CONTRACT_V1.md`

## Frozen implementation artifacts

- Data builder commit: `feeb197889a79b930b028ca5dcf0645fd0f86ffc`
  - `research/harvest_15m_builder_v1.py`
- Evaluator commit: `24cb70e439fddc989aacc02b5df750ca9c280669`
  - `research/harvest_15m_evaluator_v1.py`
- Causal/execution test commit: `44fd4cdc279ed5768c8e3937a11a188fbd1dfd38`
  - `tests/test_harvest_15m_v1.py`
- Tick schedule artifact: `research/UPBIT_KRW_TICK_SCHEDULE_V1.json`

No primary 2025-01-01 through 2026-06-30 outcome score has been opened through this research branch as of this freeze.

## Execution choices frozen here

The parent contract required the exact builder, cost implementation, and evaluator to be frozen before opening the independent interval. The following implementation details are now fixed:

1. Upbit 15m candles are fetched backward using the official minute-candle endpoint, deduplicated by UTC candle open time, then sorted ascending.
2. BTC regime is computed only from completed canonical BTC 4H candles. A BTC 4H candle becomes available at `open_time + 4h`; 15m rows use a backward as-of join on decision time.
3. `ER24` uses six 4H price steps / 24 hours and the previously frozen q30/q70 regime thresholds.
4. Primary signal uses the prior 16 completed 15m bars for box bounds and the prior 32 completed 15m absolute returns for the magnitude median. The current signal bar is excluded from both reference windows.
5. Earliest entry is the next 15m open.
6. Exit is +0.80% target, -0.60% stop, maximum four 15m bars. Same-bar stop+target ambiguity is `STOP_FIRST`.
7. Same-asset positions cannot overlap; scanning resumes only after the prior trade exits.
8. Round-trip fee is frozen at 10 bp for this historical scorecard.
9. Conservative base execution cost adds one date-correct tick as spread proxy at entry price.
10. Stress score adds one additional date-correct tick as slippage.
11. Primary bootstrap is a 10,000-resample moving block bootstrap over calendar-day trade clusters, 7-day block length, PCG64 seed `150919`; the 5th percentile of mean net trade return must be positive.
12. Chronological stability splits the realized trade sequence at its midpoint. Both halves must have positive mean net return.
13. STRONG_UP is excluded from the primary Harvest pool and is evaluated only as the preregistered routing diagnostic after the primary score is frozen.

## Anti-rescue rule

After the independent interval is opened, none of the following may change within v1: symbol universe, q30/q70 BTC regime thresholds, box lookback, 15% box-edge threshold, 32-bar magnitude window, long-only direction, TP, SL, holding horizon, fee, tick-cost treatment, bootstrap seed/block length, chronological split rule, or pass/fail gates.

A failed v1 closes only `BOX_EDGE_SHOCK_REVERSION_V1`; it does not close the broader 15m Harvest program. Any displacement-reversion, failed-breakout/reclaim, relief-bounce, or asset-selector follow-up requires a new preregistration.

## Current blocker

The Supabase SQL control connection is timing out, so the independent interval has intentionally not been opened through the database path. The builder/evaluator are frozen and ready to run once the data path is healthy. This blocker does not authorize substituting the already-exposed 2026-08-27+ pilot as validation.
