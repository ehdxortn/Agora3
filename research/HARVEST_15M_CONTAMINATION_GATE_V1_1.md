# HARVEST 15M v1.1 Contamination Gate

Status: CLEAR FOR ONE-SHOT PRIMARY VALIDATION
Date: 2026-09-19 KST
Scope: `BOX_EDGE_SHOCK_REVERSION_V1` under `HARVEST_15M_REGIME_ASSET_CONTRACT_V1`

## Search performed before opening primary outcomes

The connected Supabase research records were searched across:

- `btc_research_events`
- `btc_research_experiments`
- `btc_research_decisions`
- `research_registry`

for `HARVEST_15M`, `BOX_EDGE_SHOCK_REVERSION`, and 15-minute reversion-family terms.

## Existing records found

1. `HARVEST_15M_RESEARCH_INITIATED` — architecture/scoping only.
2. `HARVEST_15M_EXPERIMENT_0_PREREGISTERED` — a different naive one-candle 15m reversal baseline. It declared train 2021-2023, validation 2024-2025 and sealed 2026, but no recorded result/outcome event or matching experiment score was found. Its signal was simply a large completed 15m candle followed by an opposite-direction entry; it is not BOX-edge v1.
3. `HARVEST_15M_ALT_PILOT_PREREGISTERED` and `HARVEST_15M_ALT_PILOT_RESULT` — development-only Upbit pilot covering approximately 2026-08-27 through 2026-09-17. The exposed BOX pilot used a different formula (10% edge, calibration q70, bidirectional fade) and was explicitly marked non-promotional and short-sample development evidence.

No registry/event/experiment record was found showing that the exact frozen v1.1 rule below was outcome-scored on 2025-01-01 through 2026-06-30:

- six-asset universe `ARB, ENA, NEAR, POL, ONDO, SUI`;
- BTC STRONG_UP excluded from primary Harvest;
- long-only prior-16-bar BOX bottom-15% signal;
- negative signal bar with magnitude >= prior-32-bar median absolute return;
- next exact 15m open entry;
- +0.80% TP / -0.60% SL / max 60m / STOP_FIRST;
- 10bp round-trip fee + one date-correct tick spread proxy, plus one-tick stress;
- no-overlap and no missing-candle imputation;
- v1.1 frozen gates and calendar-day block bootstrap.

## Ruling

The primary interval `2025-01-01T00:00:00Z` through `2026-07-01T00:00:00Z` remains eligible for exactly one v1.1 evaluation. The earlier 2026-08-27+ pilot remains permanently excluded from the primary score.

This clearance does not imply that the broad 15m reversion idea is untouched; only that the exact v1.1 rule and its frozen economic score have not been found previously scored on the designated primary interval. Therefore the one-shot result must be interpreted as validation of this exact rule, not as an untouched test of every idea that motivated it.
