# HARVEST 15M Evaluator Freeze v1.1

Status: FROZEN BEFORE PRIMARY VALIDATION OUTCOME QUERY
Date: 2026-09-19 KST
Branch: `research/harvest-15m-v1`
Parent contract: `HARVEST_15M_REGIME_ASSET_CONTRACT_V1.md`
Supersedes: `HARVEST_15M_EVALUATOR_FREEZE_V1.md`

## Why v1.1 exists

The first freeze was followed by CI before the independent validation interval was opened. CI exposed an end-of-series off-by-one bug in the evaluator's eligibility loop. A subsequent static red-team review also found three implementation-level issues that could affect execution fidelity without changing the preregistered economic rule: tick policy was attached to the entry bar's close rather than its actual open instant; missing 15m candles could stretch row-count windows across wall-clock gaps; and the 7-day bootstrap compressed no-trade calendar days. These are pre-outcome causal/execution defects, not post-result strategy rescue.

No 2025-01-01 through 2026-06-30 Harvest v1 primary outcome score was queried before these fixes. The economic hypothesis, universe, regime thresholds, signal formula, TP, SL, horizon, fee assumption, cost stress, and pass/fail gates are unchanged.

## Frozen implementation artifacts

- Base Upbit/Supabase builder latest functional commit: `446a69c600832bb3f9cd8e0fc28908d59dc0a0ef`
  - `research/harvest_15m_builder_v1.py`
  - historical tick is evaluated at the bar open/entry instant.
- Evaluator hardening commit: `f1ea8e84e608cf872504fbaa144e2b17c9420ca6`
  - `research/harvest_15m_evaluator_v1.py`
  - final eligible signal boundary fixed;
  - 32-bar signal history must be consecutive 15m time;
  - next-bar entry and full four-bar execution path must be consecutive;
  - malformed timestamp/OHLC/regime/tick inputs fail closed;
  - moving-block bootstrap retains empty calendar days.
- Causal/execution regression tests commit: `16f9c794763b64eaf692d9faaacb93faba790a72`
  - `tests/test_harvest_15m_v1.py`
- Public parity-gated adapter commit: `8634e8a8d259454a9d30398cf77db28ef9b89ba2`
  - `research/harvest_15m_public_builder_v1.py`
- Public adapter tests commit: `6a781586751b45c4fdc99d01a13055df219cf105`
  - `tests/test_harvest_15m_public_builder_v1.py`
- Canonical BTC parity record commit: `f81ffa1303667ad08a94aaa4f3c7564997ce0189`
  - `research/BTC4H_CANONICAL_PARITY_V1.json`
- Date-correct Upbit tick schedule: `research/UPBIT_KRW_TICK_SCHEDULE_V1.json`

CI run `35406812739` completed SUCCESS on head `3e6b2599c273496235bcef587a52cab149bc7581`, covering the hardened evaluator, both builders/adapters, and regression tests before validation.

## Canonical BTC 4H parity requirement

The Supabase canonical slice `BTC`, 2024-12-01 00:00 UTC through 2026-07-01 00:00 UTC exclusive, was hashed before validation using fixed 8-decimal OHLCV serialization.

- expected rows: `3462`
- expected SHA-256: `5eb451baceaf4a975c7e8bd250e6101b34a4a229e4cd174df42a64a5acacf767`

The public adapter may proceed to Upbit validation data only if the official Binance BTCUSDT Spot monthly 4H archive reconstructs exactly the same row count, continuity, endpoints, and SHA-256. If parity fails, the primary Harvest interval remains sealed and the run stops.

## Economic rule remains unchanged

- primary domain: BTC `RANGE / TRANSITION / STRONG_DOWN`; `STRONG_UP` diagnostic only;
- universe: `ARB, ENA, NEAR, POL, ONDO, SUI`;
- long-only BOX-edge shock-reversion formula frozen in the parent contract;
- entry: next 15m open;
- TP: +0.80% gross;
- SL: -0.60% gross;
- maximum hold: four 15m bars / 60m;
- same-bar ambiguity: `STOP_FIRST`;
- base cost: 10 bp round-trip fee + one date-correct tick spread proxy;
- stress: base cost + one additional date-correct tick;
- no same-asset overlap;
- no missing-candle imputation.

## Bootstrap implementation clarification

The preregistered `7-day calendar-day trade-cluster moving block bootstrap` now explicitly retains days with zero trades between the first and last trade date. Blocks are therefore seven consecutive calendar days, not seven compressed trade-active days. The statistic remains mean net return per realized trade. Seed `150919` and 10,000 resamples remain unchanged.

## Anti-rescue rule

Once the public preflight parity passes and the independent interval is opened, v1.1 cannot change symbol universe, BTC regime thresholds, signal lookbacks/thresholds, side, TP, SL, horizon, fee, tick treatment, continuity rules, bootstrap seed/block length, chronological split, or primary pass/fail gates.

A failed `BOX_EDGE_SHOCK_REVERSION_V1` closes this exact family. It does not authorize tuning or inversion; a new mechanism requires a separately preregistered family.
