# BTC Autonomous Research Engine

BTC-only autonomous quantitative research system using OpenAI GPT-5.6 + Anthropic Claude. This repository no longer waits for Telegram `continue` prompts: one run starts a long Cloud Run Job that researches until budget, stop, blocker, or completion.

## Model hierarchy
- `gpt-5.6-luna`: high-volume prior-research scouting with web search.
- `claude-sonnet-5`: senior researcher; converts prior art + failure memory into safe ExperimentSpec.
- `gpt-5.6-sol`: Research Director; prioritizes, rejects/accepts, and controls promotion.
- `claude-opus-5`: Chief Red Team; called only after the mechanical candidate gate.
- Python/pandas: all backtests and metrics. LLMs do not decide numeric performance.

All model IDs are environment variables.

## Research lifecycle
PRIOR ART -> REPLICATION/EXTENSION -> CAUSAL EXPERIMENT -> OOS/ROBUSTNESS -> CLAUDE RED TEAM -> GPT DIRECTOR -> FAILURE MEMORY or PENDING PARITY.

The first phase deliberately builds a map of existing BTC research before proposing new experiments.

## Causal execution contract
- completed BTCUSDT 4H candle only
- decision at candle close
- earliest entry at next candle open
- chronological train/validation/untouched-test with embargo
- quantile thresholds fitted on train only
- no overlapping positions
- fees + slippage always deducted
- if stop and target touch in the same candle: STOP_FIRST
- daily on-chain data becomes available at `day + 1 UTC day`

## APEX integration
The engine never edits or deploys APEX production logic. A surviving candidate becomes a versioned Promotion Package with exact ExperimentSpec, feature/timestamp contract, execution/cost contract, OOS metrics, code/prompt version, and a deterministic parity fixture + SHA-256. It is written to `research_registry` only as `pending_parity_no_production_authority`.

APEX adoption remains a separate gate: 100% signal parity, feature parity tolerance, shadow/prospective evidence, then human approval.

## Supabase
Migration `supabase_migration.sql` creates isolated `btc_research_*` tables. RLS is enabled. `anon` and `authenticated` have no table privileges; server access uses `SUPABASE_SERVICE_ROLE_KEY`.

The engine reads existing data from `candles_4h`, `btc_futures_metrics_4h`, `funding_rates`, and `btc_onchain_daily_raw`.

## Cloud Run
The same image is deployed as:
- Service: `main.py` for START/STOP/STATUS API.
- Job: `job.py` for the long-running autonomous loop.

`POST /runs/start` creates a run and triggers the configured Cloud Run Job with a `RESEARCH_RUN_ID` override. The service account needs `run.jobs.runWithOverrides`.

## API
`GET /health`
`POST /runs/start`
`GET /runs/{run_id}`
`POST /runs/{run_id}/pause`
`POST /runs/{run_id}/resume`
`POST /runs/{run_id}/stop`
`GET /runs/{run_id}/promotion/{experiment_id}`

Configure `RESEARCH_API_SECRET`; protected routes require `X-Research-Secret`.

## Verification
`pytest -q`

Research only. No live-order code exists in this repository.
