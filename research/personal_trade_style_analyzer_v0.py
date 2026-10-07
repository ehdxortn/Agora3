#!/usr/bin/env python3
"""Private Upbit transaction-history behavior analyzer.

The script accepts a local markdown/text export and emits aggregate behavioral
statistics only. Raw fills should never be committed to this public repository.

Research-only; descriptive profile, not trading advice or live execution.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ACTIONS = {"매수", "매도"}


def _number(value: str) -> float:
    cleaned = re.sub(r"[^0-9.\-]", "", value.replace(",", ""))
    if not cleaned:
        raise ValueError(f"no numeric value: {value!r}")
    return float(cleaned)


def parse_upbit_markdown(path: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        parts = [x.strip() for x in line.strip("|").split("|")]
        if len(parts) != 10:
            continue
        fill_time, symbol, market, action, qty, price, gross, fee, net, order_time = parts
        if action not in ACTIONS:
            continue
        symbol = re.sub(r"[* ]", "", symbol)
        try:
            rows.append(
                {
                    "fill_time": pd.to_datetime(fill_time),
                    "symbol": symbol,
                    "market": market,
                    "action": action,
                    "qty": _number(qty),
                    "price": _number(price),
                    "gross": _number(gross),
                    "fee": _number(fee),
                    "net": _number(net),
                    "order_time": pd.to_datetime(order_time),
                }
            )
        except (ValueError, TypeError):
            continue
    if not rows:
        raise ValueError("no Upbit buy/sell rows parsed")
    return pd.DataFrame(rows).sort_values(["order_time", "fill_time", "symbol"]).reset_index(drop=True)


def aggregate_orders(fills: pd.DataFrame) -> pd.DataFrame:
    return (
        fills.groupby(["order_time", "symbol", "action", "price"], as_index=False)
        .agg(
            qty=("qty", "sum"),
            gross=("gross", "sum"),
            fee=("fee", "sum"),
            net=("net", "sum"),
            fill_count=("qty", "size"),
            first_fill=("fill_time", "min"),
            last_fill=("fill_time", "max"),
        )
        .sort_values(["order_time", "symbol", "action", "price"])
        .reset_index(drop=True)
    )


def exact_round_trips(orders: pd.DataFrame, qty_rtol: float = 1e-8) -> pd.DataFrame:
    """Pair only clean equal-quantity buy/sell orders.

    This intentionally excludes mixed inventory, partial exits, and pre-existing
    holdings so the short-cycle behavior profile is not contaminated.
    """
    out: list[dict[str, Any]] = []
    for symbol, group in orders.groupby("symbol"):
        buys = group[group["action"] == "매수"].sort_values("order_time")
        sells = group[group["action"] == "매도"].sort_values("order_time")
        used_sell_indexes: set[int] = set()

        for _, buy in buys.iterrows():
            tol = max(abs(float(buy["qty"])) * qty_rtol, 1e-8)
            candidates = sells[
                (sells["order_time"] >= buy["order_time"])
                & ((sells["qty"] - buy["qty"]).abs() <= tol)
                & (~sells.index.isin(used_sell_indexes))
            ]
            if candidates.empty:
                continue
            sell = candidates.iloc[0]
            used_sell_indexes.add(int(sell.name))

            capital = float(buy["net"])  # Upbit buy debit includes reported fee.
            proceeds = float(sell["net"])  # Upbit sell net is after reported fee.
            pnl = proceeds - capital
            net_return = pnl / capital if capital > 0 else np.nan

            out.append(
                {
                    "symbol": symbol,
                    "buy_order_time": buy["order_time"],
                    "sell_order_time": sell["order_time"],
                    "buy_last_fill": buy["last_fill"],
                    "sell_last_fill": sell["last_fill"],
                    "buy_price": float(buy["price"]),
                    "sell_price": float(sell["price"]),
                    "qty": float(buy["qty"]),
                    "capital": capital,
                    "pnl": pnl,
                    "net_return": net_return,
                    "order_to_order_minutes": float((sell["order_time"] - buy["order_time"]).total_seconds() / 60.0),
                    "fill_to_fill_minutes": float((sell["last_fill"] - buy["last_fill"]).total_seconds() / 60.0),
                    "buy_fill_count": int(buy["fill_count"]),
                    "sell_fill_count": int(sell["fill_count"]),
                }
            )

    if not out:
        return pd.DataFrame()
    return pd.DataFrame(out).sort_values(["buy_order_time", "symbol"]).reset_index(drop=True)


def summarize(round_trips: pd.DataFrame) -> dict[str, Any]:
    if round_trips.empty:
        return {"clean_round_trips": 0}
    r = round_trips["net_return"].astype(float)
    hold = round_trips["fill_to_fill_minutes"].astype(float)
    capital = round_trips["capital"].astype(float)
    pnl = round_trips["pnl"].astype(float)
    return {
        "clean_round_trips": int(len(round_trips)),
        "positive_after_reported_fees": int((r > 0).sum()),
        "nonpositive_after_reported_fees": int((r <= 0).sum()),
        "mean_net_return": float(r.mean()),
        "median_net_return": float(r.median()),
        "weighted_net_return": float(pnl.sum() / capital.sum()) if capital.sum() else None,
        "median_fill_to_fill_minutes": float(hold.median()),
        "mean_fill_to_fill_minutes": float(hold.mean()),
        "micro_harvest_lt_1pct": int((r < 0.01).sum()),
        "normal_1_to_3pct": int(((r >= 0.01) & (r < 0.03)).sum()),
        "larger_ge_3pct": int((r >= 0.03).sum()),
        "symbols": sorted(round_trips["symbol"].unique().tolist()),
        "note": "Clean equal-quantity round trips only; mixed/pre-existing inventory excluded.",
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--summary-output", type=Path, required=True)
    p.add_argument("--round-trips-output", type=Path)
    args = p.parse_args()

    fills = parse_upbit_markdown(args.input)
    orders = aggregate_orders(fills)
    trips = exact_round_trips(orders)
    summary = summarize(trips)
    args.summary_output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.round_trips_output:
        trips.to_csv(args.round_trips_output, index=False)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
