# PERSONAL TRADE STYLE STUDY V0

## Purpose
Model the user's actual discretionary behavior as a reference layer for the private trading copilot.
Raw transaction history must remain private and MUST NOT be committed to this public repository.

## Input
Local/private Upbit fill history only.

## Session reconstruction
Aggregate fills belonging to the same order.
Identify clean round trips only when bought and sold quantities match within tolerance.
Treat pre-existing inventory and mixed inventory separately so it does not contaminate short-cycle behavior.

## Initial behavioral measurements
For each clean round trip:
- asset
- entry price
- exit price
- net return after reported Upbit fees
- fill-to-fill holding minutes
- capital deployed
- number of fills
- whether the trade is a micro-harvest (<1%), normal harvest (1-3%), or larger tactical swing (>3%)
- BTC regime at entry
- 15m/1h asset state at entry
- MFE/MAE after entry when market history is available

## Copilot use
This profile is descriptive, not a strategy by itself.

Use it to answer:
- Does a candidate resemble the user's profitable historical setups?
- Is the current expected move large enough relative to the user's usual holding time and fees?
- Is the user likely to exit too early because the market is actually in a strong trend?
- Is the user adding risk in a regime where prior additions were poor?

## Privacy rule
Never write raw fills, account identifiers, balances, or exact private position history to this repository.
Only code and generic methodology belong here.
