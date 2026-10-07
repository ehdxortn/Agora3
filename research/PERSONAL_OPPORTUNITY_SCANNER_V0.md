# PERSONAL OPPORTUNITY SCANNER V0

## Purpose
Shadow-only market scanner for the user's private trading copilot.

It does NOT issue BUY orders.
It narrows the market to liquid Upbit KRW assets that also have active Binance USDT spot markets, then records causal features that may later support pre-expansion ranking.

## Current role
The scanner answers:
- Which liquid dual-listed coins are worth looking at now?
- Which are already late?
- Which satisfy the research-only Drawdown -> Reclaim V1 precursor?
- What 15m / 1h state is visible before any future outcome is known?

## Universe
At each run:
1. fetch active Upbit KRW markets;
2. fetch active Binance USDT spot markets;
3. intersect by base asset symbol;
4. rank by Upbit 24h KRW turnover;
5. inspect the top 30 dual-listed assets.

Symbol mappings that require aliases/rebrands are excluded until explicitly audited.

## Causal snapshot features
For each inspected asset:
- Upbit 15m return;
- Upbit 1h return;
- Upbit trailing 4h return;
- distance to prior 24h high;
- position inside prior 24h high-low range;
- Upbit 15m turnover ratio vs previous 32 bars;
- Upbit 1h turnover ratio vs previous 24 bars;
- Binance 1h return;
- Binance minus Upbit 1h return spread;
- Upbit 24h KRW turnover;
- Binance 24h USDT quote turnover.

## Research flags
LATE_ALREADY_MOVED:
- Upbit trailing 4h return >= +3%.

DRAWDOWN_RECLAIM_V1:
- trailing 4h return < +3%;
- distance to prior 24h high <= -5.356%;
- current 1h return > 0;
- current range position >= 0.25.

The V1 flag remains research-only until independent replication passes.

## Output
A compact JSON/CSV shadow watchlist.
No trade execution.
No claim that the top row is profitable.
Future research will compare each snapshot with 15m/30m/60m/4h realized outcomes.

## Future extensions
- 15m pre-pump ranker;
- actual spread/order-book;
- taker imbalance;
- OI/funding;
- sector sympathy;
- user-specific setup similarity;
- BTC regime routing;
- automated shadow outcome audit.
