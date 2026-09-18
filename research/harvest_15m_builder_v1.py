#!/usr/bin/env python3
"""Research-only data builder for HARVEST 15M Regime x Asset Contract v1.

Backfills the frozen six Upbit KRW 15m markets, joins only the latest fully
completed BTC 4H regime, applies the date-correct KRW tick schedule, and emits
canonical CSV + SHA-256 audit artifacts. Production tables are never changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from supabase import create_client

UNIVERSE = ("ARB", "ENA", "NEAR", "POL", "ONDO", "SUI")
START_UTC = pd.Timestamp("2025-01-01T00:00:00Z")
END_UTC = pd.Timestamp("2026-07-01T00:00:00Z")
UPBIT_ENDPOINT = "https://api.upbit.com/v1/candles/minutes/15"
Q30 = 0.217603904561857
Q70 = 0.583593446436297


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def to_utc(value: Any) -> pd.Timestamp:
    t = pd.Timestamp(value)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


class TickSchedule:
    def __init__(self, path: Path):
        self.path = path
        self.raw = json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _tick_from_bands(bands: list[dict[str, Any]], price: float) -> float:
        for b in bands:
            lo = float(b["min_krw"])
            hi = None if b["max_krw"] is None else float(b["max_krw"])
            if price >= lo and (hi is None or price < hi):
                return float(b["tick_krw"])
        raise ValueError(f"no tick band for price={price}")

    def tick(self, symbol: str, ts: Any, price: float) -> float:
        t = to_utc(ts)
        p = float(price)
        if not np.isfinite(p) or p <= 0:
            raise ValueError(f"invalid price {price}")

        active = []
        for rule in self.raw["rules"]:
            start = pd.Timestamp(rule["effective_from"]).tz_convert("UTC")
            end = pd.Timestamp(rule["effective_until"]).tz_convert("UTC") if rule["effective_until"] else None
            assets = rule["assets"]
            applies = assets == "ALL_RESEARCH_UNIVERSE" or symbol in assets
            if applies and start <= t and (end is None or t < end):
                active.append(rule)

        for rule in active:
            if "override" in rule:
                o = rule["override"]
                if float(o["min_krw"]) <= p < float(o["max_krw"]):
                    return float(o["tick_krw"])

        full = [r for r in active if "bands" in r]
        if full:
            return self._tick_from_bands(full[-1]["bands"], p)

        # Inherited band table: choose the latest prior full-market table.
        prior = []
        for rule in self.raw["rules"]:
            if "bands" not in rule:
                continue
            start = pd.Timestamp(rule["effective_from"]).tz_convert("UTC")
            if start <= t:
                prior.append((start, rule))
        if not prior:
            raise ValueError(f"no inherited tick rule for {symbol=} {t=}")
        prior.sort(key=lambda x: x[0])
        return self._tick_from_bands(prior[-1][1]["bands"], p)


def http_json(url: str, timeout: float = 30.0) -> Any:
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "Agora3-HarvestResearch/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_upbit_15m(symbol: str, sleep_seconds: float = 0.14) -> pd.DataFrame:
    market = f"KRW-{symbol}"
    cursor = END_UTC
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    while cursor > START_UTC:
        params = urllib.parse.urlencode(
            {
                "market": market,
                "count": 200,
                "to": cursor.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
        data = http_json(f"{UPBIT_ENDPOINT}?{params}")
        if not data:
            break
        oldest: pd.Timestamp | None = None
        for x in data:
            ts = pd.Timestamp(x["candle_date_time_utc"], tz="UTC")
            oldest = ts if oldest is None or ts < oldest else oldest
            if not (START_UTC <= ts < END_UTC):
                continue
            key = ts.isoformat()
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "symbol": symbol,
                    "open_time": ts,
                    "open": float(x["opening_price"]),
                    "high": float(x["high_price"]),
                    "low": float(x["low_price"]),
                    "close": float(x["trade_price"]),
                    "base_volume": float(x.get("candle_acc_trade_volume") or 0.0),
                    "quote_volume": float(x.get("candle_acc_trade_price") or 0.0),
                }
            )
        if oldest is None or oldest <= START_UTC:
            break
        cursor = oldest - pd.Timedelta(seconds=1)
        time.sleep(sleep_seconds)

    if not rows:
        return pd.DataFrame(columns=["symbol", "open_time", "open", "high", "low", "close", "base_volume", "quote_volume"])
    return pd.DataFrame(rows).sort_values("open_time").drop_duplicates("open_time", keep="last").reset_index(drop=True)


def load_btc_4h() -> pd.DataFrame:
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
    client = create_client(url, key)
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        chunk = (
            client.table("candles_4h")
            .select("symbol,open_time,open,high,low,close,volume")
            .eq("symbol", "BTC")
            .order("open_time")
            .range(start, start + 999)
            .execute()
            .data
            or []
        )
        rows.extend(chunk)
        if len(chunk) < 1000:
            break
        start += 1000
    if not rows:
        raise RuntimeError("candles_4h has no BTC rows")
    f = pd.DataFrame(rows)
    f["open_time"] = pd.to_datetime(f["open_time"], utc=True, format="mixed")
    for c in ("open", "high", "low", "close", "volume"):
        f[c] = pd.to_numeric(f[c], errors="coerce")
    return f.sort_values("open_time").drop_duplicates("open_time", keep="last").reset_index(drop=True)


def btc_regime_frame(btc: pd.DataFrame) -> pd.DataFrame:
    b = btc.copy().sort_values("open_time").reset_index(drop=True)
    b["btc_decision_time"] = b["open_time"] + pd.Timedelta(hours=4)
    b["ret24"] = b["close"] / b["close"].shift(6) - 1.0
    path = b["close"].diff().abs().rolling(6, min_periods=6).sum()
    b["er24"] = (b["close"] - b["close"].shift(6)).abs() / path.replace(0, np.nan)
    b["btc_regime"] = np.select(
        [
            b["er24"] <= Q30,
            (b["er24"] >= Q70) & (b["ret24"] > 0),
            (b["er24"] >= Q70) & (b["ret24"] < 0),
        ],
        ["RANGE", "STRONG_UP", "STRONG_DOWN"],
        default="TRANSITION",
    )
    return b[["btc_decision_time", "er24", "ret24", "btc_regime"]].dropna(subset=["er24", "ret24"])


def join_causal(candles: pd.DataFrame, regimes: pd.DataFrame, ticks: TickSchedule) -> pd.DataFrame:
    c = candles.copy().sort_values("open_time").reset_index(drop=True)
    c["decision_time"] = c["open_time"] + pd.Timedelta(minutes=15)
    out = pd.merge_asof(
        c.sort_values("decision_time"),
        regimes.sort_values("btc_decision_time"),
        left_on="decision_time",
        right_on="btc_decision_time",
        direction="backward",
        allow_exact_matches=True,
    )
    out["tick_krw"] = [ticks.tick(str(s), t, float(p)) for s, t, p in zip(out["symbol"], out["decision_time"], out["open"])]
    out["tick_bp"] = out["tick_krw"] / out["open"] * 10000.0
    return out


def audit_frame(f: pd.DataFrame) -> dict[str, Any]:
    if f.empty:
        return {"rows": 0}
    x = f.sort_values("open_time")
    gaps = x["open_time"].diff().dropna()
    bad_gaps = gaps[gaps != pd.Timedelta(minutes=15)]
    return {
        "rows": int(len(x)),
        "first_open_time": x["open_time"].iloc[0].isoformat(),
        "last_open_time": x["open_time"].iloc[-1].isoformat(),
        "duplicate_open_times": int(x["open_time"].duplicated().sum()),
        "non_15m_gaps": int(len(bad_gaps)),
        "largest_gap_minutes": float(bad_gaps.max() / pd.Timedelta(minutes=1)) if len(bad_gaps) else 15.0,
        "null_regime_rows": int(x["btc_regime"].isna().sum()),
        "ohlc_incoherent_rows": int(((x["high"] < x[["open", "close"]].max(axis=1)) | (x["low"] > x[["open", "close"]].min(axis=1)) | (x["high"] < x["low"])).sum()),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--tick-schedule", type=Path, default=Path(__file__).with_name("UPBIT_KRW_TICK_SCHEDULE_V1.json"))
    p.add_argument("--sleep-seconds", type=float, default=0.14)
    args = p.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    ticks = TickSchedule(args.tick_schedule)
    regimes = btc_regime_frame(load_btc_4h())
    combined: list[pd.DataFrame] = []
    audit: dict[str, Any] = {
        "contract": "HARVEST_15M_REGIME_ASSET_CONTRACT_V1",
        "window": [START_UTC.isoformat(), END_UTC.isoformat()],
        "tick_schedule_sha256": sha256_file(args.tick_schedule),
        "assets": {},
    }

    for symbol in UNIVERSE:
        joined = join_causal(fetch_upbit_15m(symbol, args.sleep_seconds), regimes, ticks)
        path = args.out_dir / f"{symbol}_15m_regime_v1.csv"
        joined.to_csv(path, index=False, date_format="%Y-%m-%dT%H:%M:%S.%fZ", float_format="%.12g")
        item = audit_frame(joined)
        item["sha256"] = sha256_file(path)
        audit["assets"][symbol] = item
        combined.append(joined)

    all_rows = pd.concat(combined, ignore_index=True).sort_values(["open_time", "symbol"])
    combined_path = args.out_dir / "upbit_15m_regime_v1.csv"
    all_rows.to_csv(combined_path, index=False, date_format="%Y-%m-%dT%H:%M:%S.%fZ", float_format="%.12g")
    audit["combined_rows"] = int(len(all_rows))
    audit["combined_sha256"] = sha256_file(combined_path)
    audit_path = args.out_dir / "upbit_15m_regime_v1_audit.json"
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
