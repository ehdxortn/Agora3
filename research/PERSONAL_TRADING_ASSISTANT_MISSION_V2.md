# PERSONAL TRADING ASSISTANT MISSION V2

## Status
Research-only mission pivot. This supersedes "report sales first" as the primary objective.
Existing validated research artifacts remain usable evidence, but no production/live-order authority is granted.

## Primary Objective
Build a personal decision-support system for the user's own discretionary trading.

The system must:
1. Assist the user's actual trading method rather than replace it.
2. Distinguish strong trend conditions from non-trend conditions before choosing the trading clock.
3. In strong uptrends, support longer holds instead of prematurely harvesting small gains.
4. In range/dead/non-strong-up markets, support repeated short-horizon harvesting using 15m execution logic.
5. Continuously scan other liquid assets for emerging opportunities.
6. Learn precursor patterns that tend to occur BEFORE rapid upward expansions so candidates can be surfaced before the move, not after it.
7. Rank candidates and explain why they are interesting, with invalidation/risk context.
8. Never auto-place orders unless the mission is explicitly changed later.

## Personalized Architecture

### A. Market Regime Router
BTC remains the market-state anchor.
- Strong trend up -> TREND RIDER support.
- Non-strong-up -> HARVEST / tactical mode.
- Strong down -> only specialized rebound/relief-bounce setups; no blind dip buying.

Higher timeframes are for regime selection, not scalp timing.
15m is the primary tactical clock for short trades.
Lower-timeframe/order-book data may be used for execution realism and confirmation.

### B. Personal Trade Assistant
Learn from the user's actual fills and behavior:
- entry timing
- holding time
- typical gross/net target
- averaging behavior
- exit timing
- market conditions where the user performs well or poorly
- opportunity-cost errors (e.g. exiting too early in strong trends)
- adverse patterns (e.g. adding while BTC regime is deteriorating)

The assistant should output:
- preferred mode: HOLD / TREND RIDER / HARVEST / WAIT
- candidate asset
- entry zone
- invalidation
- tactical target structure
- whether the setup matches the user's historically successful behavior
- what would make the setup no longer attractive

### C. Cross-Asset Opportunity Scanner
Universe priority:
- Upbit tradable
- preferably Binance + Upbit dual listing
- meaningful liquidity/turnover
- real operating project or established network
- exclude structurally dead/illiquid assets

Scanner features should include, when available:
- 15m/1h relative volume and turnover acceleration
- price compression then expansion
- local range position / failed breakdown / reclaim
- distance from VWAP / EMA / recent high
- cross-exchange lead-lag
- Upbit vs Binance basis / KRW premium dynamics
- taker buy/sell imbalance
- order-book imbalance and spread
- OI/funding changes for derivatives-listed assets
- BTC regime and BTC impulse
- sector/peer sympathy
- recent realized volatility and change in volatility

### D. Pre-Pump Pattern Lab
Goal: detect statistically repeatable precursor states before rapid upward expansions.

This is NOT "find coins that already pumped".

Create event labels using future outcomes only for labeling:
- t -> t+15m
- t -> t+30m
- t -> t+60m
- t -> t+4h

Candidate event families:
- rapid return expansion
- volume/turnover shock
- breakout from compression
- reclaim after failed breakdown
- cross-exchange lead signal
- OI + spot-volume joint acceleration
- BTC-stable alt-specific ignition
- sector sympathy ignition

All predictive features must be cut off at time t.
No post-event volume, high, close, or order-book information may leak into the feature set.

Negative controls are mandatory:
- same asset / same regime / same time-of-day non-pump windows
- near-miss events
- pumps that immediately fail
- BTC-led beta moves vs asset-specific moves

### E. Candidate Ranker
Do not require a binary "BUY" prediction.
Rank the best few current candidates by:
Expected opportunity = estimated forward MFE / realistic execution cost
adjusted by:
- probability of setup success
- liquidity/fill quality
- downside MAE
- BTC regime compatibility
- asset-specific historical fit
- pattern novelty / uncertainty

Primary output should be a short actionable watchlist, not a long market report.

## Research Metrics
For Harvest:
- net bps/trade
- net bps/exposure hour
- trades/week
- median net return
- edge/cost ratio
- MDD
- consecutive loss distribution
- stress under higher fees/slippage

For Pre-Pump Scanner:
- precision@K
- recall of top forward-return events
- median forward MFE for top-ranked candidates
- MAE before MFE
- lead time before expansion
- false-positive rate
- lift vs random and vs simple relative-volume baseline
- performance by BTC regime
- performance by asset
- performance after realistic spread/fees/slippage
- stability across chronological OOS windows

## Anti-Overfit Rules
- Event definitions and primary horizons must be preregistered before validation.
- Train/validation/test are chronological.
- Exact event labels may use future data; features may not.
- No tuning on sealed test.
- Failed families remain recorded.
- A family failure does not terminate the mission.
- Promotion requires out-of-sample stability and execution-cost survival.
- Production APEX remains untouched during research.

## Priority Order From This Pivot
1. Preserve current Harvest 15m v1.1 as a completed/ongoing research branch, not the mission itself.
2. Build the personal trade-style dataset from actual transaction history.
3. Build a dual-listed Upbit/Binance opportunity universe.
4. Define pump-event labels and negative controls.
5. Run precursor feature studies.
6. Build a ranker for "what should I watch/buy before expansion?"
7. Shadow-test recommendations before any real-money reliance.

## Final Product Concept
The target is not a generic paid report.

It is a private trading copilot that answers:
- What market game are we in?
- Should I hold longer or scalp?
- Which coins are worth watching right now?
- Which candidates are showing pre-expansion behavior?
- Is this move already late, or still early?
- What invalidates the idea?
- Does this setup resemble trades I historically execute well?
