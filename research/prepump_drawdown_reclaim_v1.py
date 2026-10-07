#!/usr/bin/env python3
"""Independent public-data replication for PREPUMP_DRAWDOWN_RECLAIM_V1.

Research-only. No live orders, no production writes, no Supabase writes.
The rule and pass gates are frozen in PREPUMP_DRAWDOWN_RECLAIM_V1.md.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import time
import urllib.error
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from harvest_15m_public_builder_v1 import (
    archive_timestamp_to_utc,
    month_range,
    robust_get_bytes,
    robust_get_json,
)

START = pd.Timestamp("2024-01-01T00:00:00Z")
END = pd.Timestamp("2026-01-01T00:00:00Z")
UNIVERSE = ("ARB", "ENA", "NEAR", "ONDO", "POL", "SUI")
UPBIT_ENDPOINT = "https://api.upbit.com/v1/candles/minutes/60"
BINANCE_ROOT = "https://data.binance.vision/data/spot/monthly/klines"

DIST_HIGH_MAX = -0.05356
RET1_MIN = 0.0
RANGE_POS_MIN = 0.25
RET4_MAX = 0.03
PUMP_MFE = 0.05


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_binance_1h(symbol: str) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    market = f"{symbol}USDT"
    rows: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for month in month_range(START, END):
        name = f"{market}-1h-{month}.zip"
        url = f"{BINANCE_ROOT}/{market}/1h/{name}"
        try:
            payload = robust_get_bytes(url)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                audit.append({"file": name, "status": "NOT_LISTED_OR_MISSING"})
                continue
            raise

        parsed = 0
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if len(names) != 1:
                raise RuntimeError(f"expected one CSV in {name}, got {names}")
            raw_csv = zf.read(names[0]).decode("utf-8")

        for row in csv.reader(io.StringIO(raw_csv)):
            if not row or not row[0].strip().lstrip("-").isdigit():
                continue
            if len(row) < 8:
                raise RuntimeError(f"short Binance kline row in {name}")
            ts = archive_timestamp_to_utc(row[0])
            if START <= ts < END:
                rows.append(
                    {
                        "open_time": ts,
                        "b_open": float(row[1]),
                        "b_high": float(row[2]),
                        "b_low": float(row[3]),
                        "b_close": float(row[4]),
                        "b_volume": float(row[5]),
                        "b_quote_volume": float(row[7]),
                    }
                )
                parsed += 1
        audit.append(
            {
                "file": name,
                "status": "OK",
                "zip_sha256": hashlib.sha256(payload).hexdigest(),
                "rows": parsed,
            }
        )

    if not rows:
        return pd.DataFrame(), audit
    frame = (
        pd.DataFrame(rows)
        .sort_values("open_time")
        .drop_duplicates("open_time", keep="last")
        .reset_index(drop=True)
    )
    return frame, audit


def fetch_upbit_1h(symbol: str, sleep_seconds: float) -> pd.DataFrame:
    market = f"KRW-{symbol}"
    cursor = END
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    while cursor > START:
        params = urllib.parse.urlencode(
            {
                "market": market,
                "count": 200,
                "to": cursor.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
        try:
            data = robust_get_json(f"{UPBIT_ENDPOINT}?{params}")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return pd.DataFrame()
            raise
        if not data:
            break

        oldest: pd.Timestamp | None = None
        for x in data:
            ts = pd.Timestamp(x["candle_date_time_utc"], tz="UTC")
            oldest = ts if oldest is None or ts < oldest else oldest
            if not (START <= ts < END):
                continue
            key = ts.isoformat()
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "open_time": ts,
                    "u_open": float(x["opening_price"]),
                    "u_high": float(x["high_price"]),
                    "u_low": float(x["low_price"]),
                    "u_close": float(x["trade_price"]),
                    "u_volume": float(x.get("candle_acc_trade_volume") or 0.0),
                    "u_trade_value": float(x.get("candle_acc_trade_price") or 0.0),
                }
            )

        if oldest is None or oldest <= START:
            break
        cursor = oldest - pd.Timedelta(seconds=1)
        time.sleep(sleep_seconds)

    if not rows:
        return pd.DataFrame()
    return (
        pd.DataFrame(rows)
        .sort_values("open_time")
        .drop_duplicates("open_time", keep="last")
        .reset_index(drop=True)
    )


def build_symbol(symbol: str, sleep_seconds: float) -> tuple[pd.DataFrame, dict[str, Any]]:
    upbit = fetch_upbit_1h(symbol, sleep_seconds)
    binance, b_sources = fetch_binance_1h(symbol)
    if upbit.empty or binance.empty:
        return pd.DataFrame(), {
            "symbol": symbol,
            "upbit_rows": int(len(upbit)),
            "binance_rows": int(len(binance)),
            "aligned_rows": 0,
            "status": "INSUFFICIENT_MARKET_HISTORY",
            "binance_sources": b_sources,
        }

    joined = upbit.merge(binance, on="open_time", how="inner").sort_values("open_time")
    if joined.empty:
        return joined, {
            "symbol": symbol,
            "upbit_rows": int(len(upbit)),
            "binance_rows": int(len(binance)),
            "aligned_rows": 0,
            "status": "NO_ALIGNED_ROWS",
            "binance_sources": b_sources,
        }

    # Exact hourly grid. Missing observations remain NaN; nothing is forward-filled.
    full_index = pd.date_range(joined["open_time"].min(), joined["open_time"].max(), freq="1h", tz="UTC")
    joined = joined.set_index("open_time").reindex(full_index)
    joined.index.name = "open_time"
    joined["symbol"] = symbol

    c = joined["u_close"]
    h = joined["u_high"]
    l = joined["u_low"]

    joined["ret1"] = c / c.shift(1) - 1.0
    joined["ret4"] = c / c.shift(4) - 1.0
    joined["prior24_high"] = h.shift(1).rolling(24, min_periods=24).max()
    joined["prior24_low"] = l.shift(1).rolling(24, min_periods=24).min()
    width = joined["prior24_high"] - joined["prior24_low"]
    joined["dist_prior24_high"] = c / joined["prior24_high"] - 1.0
    joined["range_pos24"] = (c - joined["prior24_low"]) / width.replace(0, np.nan)

    future_highs = pd.concat([h.shift(-i) for i in range(1, 5)], axis=1)
    future_lows = pd.concat([l.shift(-i) for i in range(1, 5)], axis=1)
    # Require all four future bars, not a partial max/min.
    joined["future_mfe4"] = future_highs.max(axis=1, skipna=False) / c - 1.0
    joined["future_mae4"] = future_lows.min(axis=1, skipna=False) / c - 1.0

    joined["early_pump4"] = (
        (joined["future_mfe4"] >= PUMP_MFE)
        & (joined["ret4"] < RET4_MAX)
    )
    joined["candidate_v1"] = (
        (joined["ret4"] < RET4_MAX)
        & (joined["dist_prior24_high"] <= DIST_HIGH_MAX)
        & (joined["ret1"] > RET1_MIN)
        & (joined["range_pos24"] >= RANGE_POS_MIN)
    )

    required = [
        "u_close", "b_close", "ret1", "ret4", "prior24_high", "prior24_low",
        "dist_prior24_high", "range_pos24", "future_mfe4", "future_mae4",
    ]
    valid = joined.dropna(subset=required).reset_index()
    valid = valid[(valid["open_time"] >= START) & (valid["open_time"] < END)].copy()

    audit = {
        "symbol": symbol,
        "upbit_rows": int(len(upbit)),
        "binance_rows": int(len(binance)),
        "aligned_raw_rows": int(len(upbit.merge(binance, on="open_time", how="inner"))),
        "valid_rows": int(len(valid)),
        "first_valid": None if valid.empty else valid["open_time"].min().isoformat(),
        "last_valid": None if valid.empty else valid["open_time"].max().isoformat(),
        "status": "OK" if not valid.empty else "NO_VALID_ROWS",
        "binance_sources": b_sources,
    }
    return valid, audit


def safe_median(s: pd.Series) -> float | None:
    x = pd.to_numeric(s, errors="coerce").dropna()
    return None if x.empty else float(x.median())


def summarize(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "observations": 0,
            "events": 0,
            "base_rate": None,
            "candidate_count": 0,
            "candidate_events": 0,
            "candidate_rate": None,
            "lift": None,
        }
    cand = frame[frame["candidate_v1"]]
    base = float(frame["early_pump4"].mean())
    cand_rate = None if cand.empty else float(cand["early_pump4"].mean())
    return {
        "observations": int(len(frame)),
        "events": int(frame["early_pump4"].sum()),
        "base_rate": base,
        "candidate_count": int(len(cand)),
        "candidate_events": int(cand["early_pump4"].sum()) if not cand.empty else 0,
        "candidate_rate": cand_rate,
        "lift": None if cand_rate is None or base <= 0 else cand_rate / base,
        "candidate_frequency": float(len(cand) / len(frame)),
        "candidate_median_mfe4": safe_median(cand["future_mfe4"]) if not cand.empty else None,
        "candidate_median_mae4": safe_median(cand["future_mae4"]) if not cand.empty else None,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--sleep-seconds", type=float, default=0.13)
    args = p.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    frames: list[pd.DataFrame] = []
    audit: dict[str, Any] = {
        "contract": "PREPUMP_DRAWDOWN_RECLAIM_V1",
        "window": [START.isoformat(), END.isoformat()],
        "universe": list(UNIVERSE),
        "assets": {},
    }

    for symbol in UNIVERSE:
        frame, item = build_symbol(symbol, args.sleep_seconds)
        audit["assets"][symbol] = item
        if not frame.empty:
            frames.append(frame)
        print(json.dumps({
            "symbol": symbol,
            "status": item["status"],
            "valid_rows": item.get("valid_rows", 0),
            "first_valid": item.get("first_valid"),
            "last_valid": item.get("last_valid"),
        }, sort_keys=True))

    if not frames:
        raise RuntimeError("no usable aligned replication data")

    allf = pd.concat(frames, ignore_index=True).sort_values(["open_time", "symbol"]).reset_index(drop=True)
    allf["year"] = allf["open_time"].dt.year

    years = {str(y): summarize(allf[allf["year"] == y]) for y in (2024, 2025)}
    pooled = summarize(allf)

    by_asset: dict[str, Any] = {}
    for symbol in UNIVERSE:
        sf = allf[allf["symbol"] == symbol]
        by_asset[symbol] = summarize(sf)

    total_candidates = pooled["candidate_count"]
    candidate_shares = {
        s: (m["candidate_count"] / total_candidates if total_candidates else 0.0)
        for s, m in by_asset.items()
    }
    asset_good = [
        s for s, m in by_asset.items()
        if m["candidate_count"] >= 20 and m["lift"] is not None and m["lift"] >= 1.0
    ]

    year_gate: dict[str, str] = {}
    for y, m in years.items():
        if m["candidate_events"] < 30:
            year_gate[y] = "INSUFFICIENT"
        elif m["lift"] is not None and m["lift"] >= 1.50:
            year_gate[y] = "PASS"
        else:
            year_gate[y] = "FAIL"

    cross_asset_pass = (
        len(asset_good) >= 4
        and max(candidate_shares.values(), default=0.0) <= 0.50
        and pooled["candidate_rate"] is not None
        and pooled["base_rate"] is not None
        and pooled["candidate_rate"] > pooled["base_rate"]
    )
    if all(x == "PASS" for x in year_gate.values()) and cross_asset_pass:
        status = "PASS"
    elif any(x == "INSUFFICIENT" for x in year_gate.values()):
        status = "INSUFFICIENT"
    else:
        status = "REJECT"

    result = {
        "contract": "PREPUMP_DRAWDOWN_RECLAIM_V1",
        "rule": {
            "dist_prior24_high_lte": DIST_HIGH_MAX,
            "ret1_gt": RET1_MIN,
            "range_pos24_gte": RANGE_POS_MIN,
            "ret4_lt": RET4_MAX,
        },
        "label": {
            "future_4h_mfe_gte": PUMP_MFE,
            "ret4_lt": RET4_MAX,
        },
        "years": years,
        "pooled": pooled,
        "by_asset": by_asset,
        "candidate_shares": candidate_shares,
        "assets_with_n20_and_lift_ge1": asset_good,
        "year_gate": year_gate,
        "cross_asset_pass": cross_asset_pass,
        "replication_status": status,
    }

    candidates = allf[allf["candidate_v1"]].copy()
    keep = [
        "open_time", "symbol", "u_close", "ret1", "ret4",
        "dist_prior24_high", "range_pos24", "future_mfe4", "future_mae4", "early_pump4",
    ]
    candidates[keep].to_csv(
        args.out_dir / "PREPUMP_DRAWDOWN_RECLAIM_V1_CANDIDATES.csv",
        index=False,
        date_format="%Y-%m-%dT%H:%M:%SZ",
        float_format="%.12g",
    )
    result_path = args.out_dir / "PREPUMP_DRAWDOWN_RECLAIM_V1_RESULT.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    audit["combined_valid_rows"] = int(len(allf))
    audit["candidate_rows"] = int(len(candidates))
    audit["result_sha256"] = sha256_file(result_path)
    (args.out_dir / "PREPUMP_DRAWDOWN_RECLAIM_V1_AUDIT.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
