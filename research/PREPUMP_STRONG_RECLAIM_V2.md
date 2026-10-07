# PREPUMP STRONG RECLAIM V2 — INDEPENDENT STAGE-2 TEST

## Purpose
Improve precision inside the independently replicated V1 precursor state.

V1 already passed on 2024-2025:
deep drawdown + positive 1h reclaim + recovery off the prior-24h floor.

V2 asks whether a **stronger reclaim into the prior-24h range** further enriches rapid upward expansion.

## Discovery / threshold source
EXPOSED 2026 only.

Among V1 candidates:
- development: 2026-01-01 through 2026-06-30;
- frozen 80th percentile of range_pos24 = **0.481992337164751**;
- development high-reclaim event rate = 9.917%, lift ~2.07x vs V1-candidate base;
- secondary 2026-07 through 2026-09 check: 18/95 events = 18.947%, lift ~1.69x vs V1-candidate base.

Those observations are discovery evidence only.

## Frozen V2 rule
A V2 candidate must first satisfy all V1 conditions:
- trailing 4h return < +3%;
- distance from prior 24h high <= -5.356%;
- current 1h return > 0;
- range_pos24 >= 0.25.

Then add:
- **range_pos24 >= 0.481992337164751**.

No volume, Binance-lead, BTC-regime, or other filter is added.

## Outcome
Same V1 outcome:
EARLY_PUMP_4H = future 4h MFE >= +5%, while trailing 4h return at decision time is < +3%.

## Independent test data
Reuse the immutable public-data V1 replication artifact from workflow run 37600022411.
This avoids re-downloading/reconstructing data and prevents accidental rule drift.

Test separately:
- calendar 2024;
- calendar 2025.

2024-2025 V1 outcomes were used only to establish V1 as a precursor family.
The V2 range-position threshold and direction were fixed from 2026 before inspecting any 2024-2025 V2 stratification.

## Primary comparison
Within the V1 candidate pool:
V2 event rate / V1 candidate event rate.

This is a stage-2 precision test, not a comparison to the unconditional market base.

## Pass gate
PASS only if:
- stage-2 lift >= 1.25x in both 2024 and 2025;
- V2 has >=15 events in each year;
- pooled V2 events >=40;
- pooled V2 candidate event rate > pooled V1 candidate event rate;
- >=4 assets have >=20 V2 candidates;
- no asset contributes >50% of V2 candidates.

Otherwise REJECT or INSUFFICIENT.

## Interpretation
A pass means strong reclaim is a validated precision layer on top of V1.
It still does not become a standalone buy signal.
The next layer is 15m timing and prospective shadow testing.
