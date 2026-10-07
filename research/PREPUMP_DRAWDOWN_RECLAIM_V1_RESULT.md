# PREPUMP DRAWDOWN -> RECLAIM V1 — INDEPENDENT REPLICATION RESULT

Status: **PASS as a precursor feature family; NOT a standalone trading signal**

Workflow run: `37600022411`

## Frozen rule
At completed 1h bar:
- trailing 4h return < +3%;
- close is at least 5.356% below the prior 24h high;
- current 1h return > 0;
- close has recovered to at least 25% of the prior-24h high-low range.

Outcome label:
- future 4h maximum favorable excursion >= +5%;
- trailing 4h return at decision time < +3%.

The rule was discovered on exposed 2026 data, preregistered, then replicated from public Upbit/Binance data on 2024-2025.

## Independent result

| Period | Observations | Base event rate | Candidates | Candidate events | Candidate rate | Lift |
|---|---:|---:|---:|---:|---:|---:|
| 2024 | 28,526 | 4.50% | 1,251 | 107 | 8.55% | **1.90x** |
| 2025 | 44,740 | 2.44% | 1,342 | 67 | 4.99% | **2.05x** |
| Pooled | 73,266 | 3.24% | 2,593 | 174 | 6.71% | **2.07x** |

Both frozen calendar-year gates passed and the cross-asset gate passed.

Pooled candidate median future 4h MFE was about +1.40%; median future 4h MAE was about -1.59%.
Therefore the state has useful event lift but still has many false positives.

## Cross-asset lift
- ARB: 2.36x
- ENA: 1.06x
- NEAR: 2.36x
- ONDO: 2.53x
- POL: 2.57x
- SUI: 1.61x

All six were >=1.0x in the pooled replication sample. No single asset dominated candidate count.

## Interpretation
This is the first independently replicated precursor family in the personal-copilot track.

It does **not** justify buying every occurrence:
- only 6.71% of candidates reached the +5%/4h event definition;
- it is best used as a high-recall candidate filter;
- later layers must improve timing/precision and control drawdown.

## Next research
1. Use this state as a first-stage screen.
2. Develop 15m timing inside the screened state.
3. Add independent information: activity acceleration, cross-exchange lead, derivatives positioning, order-book/taker flow.
4. Rank candidates rather than emit binary BUY signals.
5. Prospectively shadow-test before real-money reliance.

Production/APEX remains untouched.
