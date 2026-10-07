# PRE-PUMP DRAWDOWN -> RECLAIM V1 — INDEPENDENT REPLICATION

## Why this exists
V0's frozen score failed.
One post-hoc mechanism survived cross-asset inspection strongly enough to justify a NEW hypothesis:
rapid upward expansions were more common while an asset remained materially below its prior 24h high.

This V1 is not a rescue of V0. It is a new, preregistered family and must be validated on historical data that was not used to discover it.

## Discovery evidence (EXPOSED; not validation)
2026-01 through 2026-09:
- development low-quintile threshold for distance from prior 24h high: -5.356%;
- low-quintile lift: ~1.89x development and ~1.93x validation;
- all six assets had validation lift >1.0 for this state.

A small exposed mechanism screen suggested that requiring a positive 1h bar plus recovery into at least the lower quarter of the prior-24h range had higher event precision than a positive bar alone.

## Frozen V1 candidate rule
At completed Upbit 1h bar t:

1. EARLY:
   trailing 4h close return < +3%.

2. DEEP DRAWDOWN:
   close_t / prior_24h_high - 1 <= -5.356%.

3. RECLAIM:
   current 1h return > 0.

4. OFF THE FLOOR:
   current close position within the prior-24h high-low range >= 0.25.

If all are true, mark PREPUMP_DRAWDOWN_RECLAIM_V1 candidate.

No activity/volume threshold is included in V1.
No Binance lead threshold is included in V1.
Those remain independent future feature families.

## Outcome label
EARLY_PUMP_4H:
- max Upbit high over t+1..t+4 >= close_t * 1.05;
- trailing 4h return at t < +3%.

Features use completed data at t only.
Future data is label-only.

## Independent replication interval
Fetch public 1h data directly from exchanges:
- 2024-01-01 through 2025-12-31 UTC;
- use each asset only after both Upbit KRW and Binance spot observations exist;
- universe: ARB, ENA, NEAR, ONDO, POL, SUI.

2026 is discovery/exposed and MUST NOT count as V1 replication evidence.

Report separately:
- replication A: calendar 2024;
- replication B: calendar 2025.

## Primary metrics
For each year and pooled:
- observations;
- EARLY_PUMP_4H events;
- base event rate;
- V1 candidate count;
- V1 candidate event rate;
- lift vs base;
- median future 4h MFE;
- median future 4h MAE;
- candidate frequency;
- per-asset candidate count/event rate/lift.

## Pass gate
V1 passes independent mechanism replication only if:
- candidate lift >= 1.50x in BOTH 2024 and 2025 where each year has >=30 candidate events;
- pooled candidate event rate > pooled base event rate;
- at least 4 assets have pooled lift >=1.0 with >=20 candidates each;
- no single asset contributes >50% of all candidates.

If calendar 2024 lacks adequate common-universe coverage, the year gate is reported INSUFFICIENT rather than forced to pass/fail.
In that case, pooled and 2025 results are descriptive only until another independent period is obtained.

## Interpretation
Even a pass does NOT mean "buy every signal".
This family is intended as one input to a candidate ranker.
A standalone precision near single digits can still be useful if it creates strong lift and is combined with other independent precursor features.

## After pass
- refine surviving rule on 15m timing;
- measure lead time and MAE-before-MFE;
- add execution costs;
- combine with independent activity, cross-exchange, OI/taker, and order-book features;
- shadow rank before real-money reliance.
