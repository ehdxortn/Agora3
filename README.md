# BTC Autonomous Research Engine

BTC-only autonomous quantitative research laboratory using OpenAI GPT-5.6 + Anthropic Claude. It is separate from `multiLLM-agent`/APEX production and does not wait for Telegram `continue` prompts.

## Hierarchy
- `gpt-5.6-luna`: bulk prior-art/web scouting.
- `claude-sonnet-5`: senior researcher converting prior art + Director directives + failure memory into a safe ExperimentSpec.
- `gpt-5.6-sol`: Research Director controlling research direction and promotion decisions.
- `claude-opus-5`: Chief Red Team, called only after the train/validation candidate gate.
- Python/pandas: all numeric testing. LLMs do not calculate strategy performance.

Model ids are environment variables.

## Research lifecycle
PRIOR ART -> REPLICATION/EXTENSION -> TRAIN/VALIDATION EXPERIMENT -> CLAUDE RED TEAM -> SCARCE SEALED HOLDOUT -> GPT DIRECTOR -> FAILURE MEMORY or PENDING PARITY.

The engine maps at least 12 BTC research families and targets at least 120 literature records before normal experimentation. A new experiment must reference checked prior-art ids; otherwise another search is forced.

## Causal contract
- DB reality: `candles_4h`/`funding_rates` use symbol `BTC`; `btc_futures_metrics_4h` uses `BTCUSDT`.
- decision only after a completed 4H candle; earliest entry is next 4H open.
- futures rows with missing/conflicting slots are excluded from derivative features.
- funding is backward-asof at decision time.
- daily on-chain data is conservatively lagged 2 UTC days by default.
- chronological train/validation/sealed-holdout + embargo; no random shuffle.
- train quantiles are fitted on train only.
- no overlapping positions; fees + slippage always deducted.
- ambiguous same-bar stop+target uses `STOP_FIRST`.

The sealed holdout is not computed during ordinary exploration. It is revealed only after the validation gate and independent Claude red-team PASS. Holdout exposures are counted and capped.

## Exact APEX promotion
A surviving candidate becomes a Promotion Package with ExperimentSpec, resolved thresholds, feature/timestamp contract, execution/cost contract, OOS metrics, Git commit id, prompt version, data fingerprint, and 80 deterministic parity vectors.

APEX can fetch the package, independently calculate those timestamps, then submit its vectors to:
`POST /runs/{run_id}/promotion/{experiment_id}/parity/verify`

Only identical timestamps/signals and feature/close values within tolerance can change the package to `PARITY_PASSED`. That status is still `shadow only`; this engine has no authority to deploy an APEX production rule or place a live order.

## Supabase
Migration `supabase_migration.sql` creates isolated `btc_research_*` tables. RLS is enabled; `anon` and `authenticated` have no table privileges. Server-side access requires the service role.

## Cloud Run
The same Docker image is used as a Service (`main.py`: START/STOP/STATUS/Parity API) and a long-running Job (`job.py`: autonomous loop). The Job receives `RESEARCH_RUN_ID` as a runtime override. `GIT_SHA` is injected at deployment so every Promotion Package identifies its research code revision.

Secrets are not stored in Git. Configure OpenAI, Anthropic, Supabase service-role and Research API secret using Cloud Run/Secret Manager before deployment.

## Cost controls
`RUN_BUDGET_USD` and a global UTC-day `DAILY_BUDGET_USD` are enforced from the usage ledger. Default examples are $10/run and $15/day. Bulk work uses cheaper models; Opus/Sol are reserved for higher-value decisions.

## Verification
GitHub Actions runs compile + pytest. Local: `pytest -q`.

Research only. No live-order code exists in this repository.
