# HARVEST 15M Regime × Asset Contract v1

Status: preregistered research contract. No production authority.
Date: 2026-09-19 KST.
Branch: `research/harvest-15m-v1`.

## 1. Research question

Can a long-only 15-minute mean-reversion/relief-bounce engine generate positive executable expectancy in BTC states where a strong 4H uptrend is absent, while a separate strong-uptrend gate preserves the option to hold longer instead of repeatedly taking small profits?

This contract formalizes the architecture:

`BTC 4H regime -> asset harvestability -> 15m setup -> execution/cost -> exit`.

The 4H clock selects the game. The 15m clock selects entries/exits. They are not required to agree directionally.

## 2. Pilot observations already exposed

The recent 2026-08-27..2026-09-17 pilot is DEVELOPMENT ONLY and can never be used as validation for this family.

Existing exploratory results after a flat 15 bp round-trip assumption showed:

- BOX-edge reversion, BTC RANGE: ARB +17.03 bp/trade (n=27), ENA +19.50 (n=24), NEAR -39.88 (n=37).
- BOX-edge reversion, BTC STRONG_DOWN: ARB +7.75 (n=20), ENA +11.36 (n=6), NEAR +24.39 (n=29).
- Z2 displacement reversion, BTC RANGE: ARB +27.98 (n=48), ENA +16.39 (n=43), NEAR -26.47 (n=58).
- Z2 displacement reversion, BTC STRONG_DOWN: ARB -11.71 (n=35), ENA -10.08 (n=20), NEAR +22.86 (n=32).

Weighted across the three pilot assets, BOX-edge reversion in STRONG_DOWN was +16.92 bp/trade after 15 bp cost over 55 trades and all three asset means were positive. This is only a mechanism lead, not evidence for promotion.

User-observed profitable short-horizon trades also occurred in STRONG_DOWN, TRANSITION, and RANGE contexts, not only in RANGE. Therefore this contract does not define `HARVEST = RANGE`.

## 3. Frozen BTC regime gate

At every 15m decision, use only the latest fully completed BTC 4H bar.

Compute 24h Kaufman-style efficiency ratio from the six completed 4H bars:

`ER24 = abs(C_t - C_{t-6}) / sum_{i=t-5..t} abs(C_i - C_{i-1})`.

Freeze the already measured research thresholds:

- RANGE: `ER24 <= 0.217603904561857`.
- high-efficiency state: `ER24 >= 0.583593446436297`.
- STRONG_UP: high-efficiency AND 24h BTC return > 0.
- STRONG_DOWN: high-efficiency AND 24h BTC return < 0.
- TRANSITION: otherwise.

Routing rule:

- STRONG_UP -> Trend-Rider domain; this Harvest contract is inactive.
- RANGE / TRANSITION / STRONG_DOWN -> Harvest domain is eligible.

No future 15m observation may change the 4H label assigned to an earlier decision.

## 4. Asset universe

Frozen Upbit KRW universe for this family:

`ARB, ENA, NEAR, POL, ONDO, SUI`.

An asset is eligible only after its Upbit KRW listing and only where complete causal 15m candles exist.

No symbol deletion is allowed because of poor results. A symbol may be absent only for documented listing/data-availability reasons.

## 5. Time split and contamination control

The recent pilot window beginning 2026-08-27 is permanently exposed development data.

Primary independent historical validation window:

- start: 2025-01-01 00:00 UTC or the asset's later listing date;
- end-exclusive: 2026-07-01 00:00 UTC.

This window must remain unopened for outcome scoring until the exact data builder, setup formula, execution-cost schedule, and evaluator hash are frozen.

If any part of 2025-01-01..2026-06-30 has already been outcome-scored for the exact same 15m family, it must be marked contaminated and replaced by an earlier untouched interval before execution.

No 2026-08-27+ pilot row may enter the primary score.

## 6. Data and causal clock

Signal data: official Upbit 15-minute candles.

BTC regime data: canonical completed BTC 4H research candles.

Decision time is the close of a completed 15m signal candle. Earliest entry is the next 15m bar open.

Never use the signal bar high/low after its close to infer a better entry.

For historical execution-cost reconstruction, use the Upbit KRW tick-size schedule that was actually effective on the trade date. Current tick rules must never be back-applied to older observations.

A versioned tick-schedule artifact with source URL/effective date/hash is required before scoring.

## 7. Primary setup: BOX-EDGE SHOCK REVERSION v1

Long-only.

At signal bar t, calculated only from bars <= t:

- rolling local box: previous 16 completed 15m bars, excluding the current signal bar for the box bounds;
- `box_low = min(low[t-16:t-1])`;
- `box_high = max(high[t-16:t-1])`;
- `box_width = box_high - box_low`, must be > 0;
- completed signal candle closes in the bottom 15% of that prior box: `(close_t - box_low) / box_width <= 0.15`;
- signal candle return is negative;
- magnitude filter: `abs(return_t) >= median(abs(return))` over the prior 32 completed 15m bars;
- no overlapping position in the same asset.

Entry: next 15m open.

This exact formula is new and is not allowed to claim the pilot BOX numbers as its own historical result.

## 8. Exit and path measurement

Primary exit is deliberately simple so the study tests the entry/routing edge before optimizing exits:

- max holding: 4 bars / 60 minutes;
- take profit: +0.80% gross from entry;
- stop: -0.60% gross from entry;
- if both stop and target are touched within the same 15m candle, use STOP_FIRST;
- otherwise exit at the fourth bar close.

Also record without affecting the primary exit:

- MFE at 15/30/45/60m;
- MAE at 15/30/45/60m;
- bars-to-MFE;
- bars-to-MAE;
- maximum favorable excursion divided by maximum adverse excursion.

No post-result TP/SL/horizon rescue is permitted under this contract.

## 9. Execution and cost model

Two scorecards are mandatory and reported separately.

### A. Conservative taker proxy

Per trade cost must include:

1. round-trip trading fee according to the applicable Upbit fee schedule;
2. one contemporaneous tick of spread proxy expressed in bp at entry price;
3. one additional tick of slippage stress in the stressed scorecard.

Because historical L1 orderbook is not available for the full validation interval, this is a conservative deterministic proxy, not a claim of exact fills.

### B. Candle-only lower-authority score

Fee-only score may be shown only as a diagnostic. It cannot pass the family by itself.

`touch == fill` is prohibited for any passive-limit interpretation.

## 10. Harvestability measurements

For every eligible asset-time observation, compute:

- tick_bp;
- rolling 24h 15m realized volatility;
- median 15m true range in bp;
- median absolute 15m return in bp;
- local 16-bar efficiency ratio;
- historical reversal rate using only prior data;
- expected move / deterministic execution-cost ratio.

These variables are descriptive in v1. They are not allowed to filter the primary setup after outcomes are seen.

Their purpose is to explain cross-asset heterogeneity and generate a separately preregistered v2 Asset Selector if warranted.

## 11. Primary gates

The family can advance to a separate sealed follow-up only if all are true on the untouched primary interval:

1. at least 150 total non-overlapping trades;
2. at least 4 assets contribute >= 20 trades each;
3. no single asset contributes > 40% of all trades;
4. pooled conservative-taker mean net return > 0;
5. pooled median net return >= 0;
6. daily-cluster moving-block bootstrap 5th percentile of mean net return > 0;
7. first chronological half mean net > 0 and second chronological half mean net > 0;
8. at least 4 of 6 asset-level mean net returns are > 0 among assets with >=20 trades;
9. additional one-tick slippage stress has mean net return >= 0;
10. STRONG_DOWN and RANGE+TRANSITION are each reported independently; neither may have mean net <= -15 bp/trade if it contains >=30 trades.

Failure of any gate closes BOX-EDGE SHOCK REVERSION v1. No threshold tuning, sign inversion, symbol deletion, horizon change, or TP/SL rescue is allowed.

A failure does not close the broader 15m Harvest program. Independent families such as failed-breakout reclaim or displacement reversion require their own preregistration.

## 12. Strong-uptrend separation test

For diagnostic falsification only, run the exact same setup in STRONG_UP after the non-STRONG-UP score is frozen.

This comparison answers whether routing is valuable. It cannot be used to tune the primary rule.

The architectural claim `STRONG_UP -> do not scalp the same way` is supported only if Harvest expectancy is materially lower in STRONG_UP than in the eligible non-STRONG-UP pool with adequate sample. If STRONG_UP sample is sparse, report INSUFFICIENT rather than infer superiority of Trend Rider.

## 13. Prohibited actions

- no production/Apex code modification;
- no live order placement;
- no current tick table applied retrospectively without effective-date reconstruction;
- no outcome-driven symbol removal;
- no opening of the sealed interval before evaluator freeze;
- no same-bar target-first optimism;
- no using the recent pilot as validation;
- no claiming passive fills from OHLC touch;
- no promotion from statistical significance alone.

## 14. Next engineering action

Build a research-only data adapter that:

1. backfills the six Upbit 15m KRW markets for the untouched interval;
2. joins each 15m signal time to the latest completed BTC 4H regime;
3. applies the date-correct KRW tick schedule;
4. emits deterministic parquet/CSV plus SHA-256 and missingness audit;
5. executes this contract once without opening any separate sealed holdout.

Production remains untouched.