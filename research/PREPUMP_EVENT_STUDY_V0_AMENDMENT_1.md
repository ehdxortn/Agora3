# PRE-PUMP EVENT STUDY V0 — AMENDMENT 1

## Timing
This amendment is recorded after inspecting only label/base-rate counts.
No feature-quintile outcome or score outcome has been inspected.

## Change
The preregistration described rolling 24h medians for several normalization terms.
The direct correlated-median SQL exceeded the database statement timeout.

For V0 only, replace these rolling medians with causal rolling 24h means:
- Upbit trade-value normalization;
- Binance quote-volume normalization;
- Upbit/Binance price-ratio normalization;
- true-range normalization.

Reason: this preserves the same causal feature families while allowing a deterministic window-function implementation over the aligned research tables.

## Unchanged
- universe;
- development/validation dates;
- EARLY_PUMP_4H label;
- 3% trailing-4h "not already pumped" condition;
- feature directions;
- quintile procedure;
- simple score components;
- pass/fail thresholds;
- no validation retuning.

This amendment must not be changed after feature outcomes are inspected.
