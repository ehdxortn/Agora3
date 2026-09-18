#!/usr/bin/env python3
"""Public-source data adapter for the frozen Harvest 15m v1 evaluator.

This adapter has one hard precondition: the reconstructed Binance BTCUSDT spot
4H slice must exactly match the pre-frozen canonical Supabase BTC 4H hash.
Only after parity passes does it fetch Upbit 15m candles.

Research-only. It does not write production or Supabase tables.
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
import urllib.request
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

import harvest_15m_builder_v1 as base

PARITY_START = pd.Timestamp("2024-12-01T00:00:00Z")
PARITY_END = pd.Timestamp("2026-07-01T00:00:00Z")
BINANCE_BASE = "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/4h"
Q8 = Decimal("0.00000001")


def robust_get_bytes(url: str, timeout: float = 45.0, attempts: int = 8) -> bytes:
    last: Exception | None = None
    for attempt in range(attempts):
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "*/*",
                "User-Agent": "Agora3-HarvestResearch/1.1",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code != 429 and not (500 <= exc.code < 600):
                raise
            retry_after = exc.headers.get("Retry-After")
            try:
                wait = float(retry_after) if retry_after else 0.0
            except ValueError:
                wait = 0.0
            time.sleep(max(wait, min(0.5 * (2**attempt), 8.0)))
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt >= attempts - 1:
                raise
            time.sleep(min(0.5 * (2**attempt), 8.0))
    raise last or RuntimeError(f"failed GET {url}")


def robust_get_json(url: str, timeout: float = 30.0, attempts: int = 8) -> Any:
    return json.loads(robust_get_bytes(url, timeout=timeout, attempts=attempts).decode("utf-8"))


def archive_timestamp_to_utc(raw: str | int) -> pd.Timestamp:
    value = int(raw)
    # Binance Spot public archives use microseconds for newer files and
    # milliseconds for older files. 4H boundaries are exactly representable
    # in either unit.
    unit = "us" if abs(value) >= 100_000_000_000_000 else "ms"
    return pd.to_datetime(value, unit=unit, utc=True)


def fixed8(value: str | float | Decimal) -> str:
    return format(Decimal(str(value)).quantize(Q8), "f")


def canonical_btc_line(
    open_time: pd.Timestamp,
    open_: str | float,
    high: str | float,
    low: str | float,
    close: str | float,
    volume: str | float,
) -> str:
    epoch_ms = int(open_time.timestamp() * 1000)
    return ",".join(
        [
            str(epoch_ms),
            fixed8(open_),
            fixed8(high),
            fixed8(low),
            fixed8(close),
            fixed8(volume),
        ]
    )


def month_range(start: pd.Timestamp, end_exclusive: pd.Timestamp) -> list[str]:
    first = start.tz_convert(None).to_period("M")
    last = (end_exclusive - pd.Timedelta(seconds=1)).tz_convert(None).to_period("M")
    return [str(p) for p in pd.period_range(first, last, freq="M")]


def fetch_binance_btc_4h() -> tuple[pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    canonical_lines: list[tuple[pd.Timestamp, str]] = []
    source_files: list[dict[str, Any]] = []

    for month in month_range(PARITY_START, PARITY_END):
        name = f"BTCUSDT-4h-{month}.zip"
        url = f"{BINANCE_BASE}/{name}"
        payload = robust_get_bytes(url)
        zip_sha = hashlib.sha256(payload).hexdigest()
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if len(names) != 1:
                raise RuntimeError(f"expected one CSV in {name}, got {names}")
            raw_csv = zf.read(names[0]).decode("utf-8")

        parsed = 0
        for row in csv.reader(io.StringIO(raw_csv)):
            if not row or not row[0].strip().lstrip("-").isdigit():
                continue
            if len(row) < 6:
                raise RuntimeError(f"short kline row in {name}: {row[:6]}")
            ts = archive_timestamp_to_utc(row[0])
            if not (PARITY_START <= ts < PARITY_END):
                continue
            line = canonical_btc_line(ts, row[1], row[2], row[3], row[4], row[5])
            canonical_lines.append((ts, line))
            rows.append(
                {
                    "open_time": ts,
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                }
            )
            parsed += 1
        source_files.append({"file": name, "sha256": zip_sha, "rows_in_parity_range": parsed})

    if not rows:
        raise RuntimeError("no Binance BTC 4H rows fetched")
    frame = (
        pd.DataFrame(rows)
        .sort_values("open_time")
        .drop_duplicates("open_time", keep="last")
        .reset_index(drop=True)
    )
    canonical_lines.sort(key=lambda x: x[0])
    if len(canonical_lines) != len(frame):
        raise RuntimeError("duplicate Binance 4H open times detected")
    payload = "\n".join(line for _, line in canonical_lines).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    gaps = frame["open_time"].diff().dropna()
    audit = {
        "rows": int(len(frame)),
        "min_open": frame["open_time"].min().isoformat(),
        "max_open": frame["open_time"].max().isoformat(),
        "sha256": digest,
        "non_4h_gaps": int((gaps != pd.Timedelta(hours=4)).sum()),
        "source_files": source_files,
    }
    return frame, audit


def verify_btc_parity(frame: pd.DataFrame, audit: dict[str, Any], parity_path: Path) -> dict[str, Any]:
    spec = json.loads(parity_path.read_text(encoding="utf-8"))
    checks = {
        "row_count": int(audit["rows"]) == int(spec["row_count"]),
        "sha256": audit["sha256"] == spec["sha256"],
        "start": frame["open_time"].min() == pd.Timestamp(spec["range_start_utc"]),
        "end": frame["open_time"].max() == pd.Timestamp(spec["range_end_exclusive_utc"]) - pd.Timedelta(hours=4),
        "continuous_4h": int(audit["non_4h_gaps"]) == 0,
    }
    passed = all(checks.values())
    result = {
        "spec": spec,
        "observed": audit,
        "checks": checks,
        "passed": passed,
    }
    if not passed:
        raise RuntimeError("BTC 4H canonical parity failed: " + json.dumps(result, sort_keys=True))
    return result


def fetch_upbit_15m_robust(symbol: str, sleep_seconds: float = 0.16) -> pd.DataFrame:
    market = f"KRW-{symbol}"
    cursor = base.END_UTC
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    while cursor > base.START_UTC:
        params = urllib.parse.urlencode(
            {
                "market": market,
                "count": 200,
                "to": cursor.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
        data = robust_get_json(f"{base.UPBIT_ENDPOINT}?{params}")
        if not data:
            break
        oldest: pd.Timestamp | None = None
        for x in data:
            ts = pd.Timestamp(x["candle_date_time_utc"], tz="UTC")
            oldest = ts if oldest is None or ts < oldest else oldest
            if not (base.START_UTC <= ts < base.END_UTC):
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
        if oldest is None or oldest <= base.START_UTC:
            break
        cursor = oldest - pd.Timedelta(seconds=1)
        time.sleep(sleep_seconds)

    if not rows:
        raise RuntimeError(f"no Upbit 15m rows for {symbol}")
    return (
        pd.DataFrame(rows)
        .sort_values("open_time")
        .drop_duplicates("open_time", keep="last")
        .reset_index(drop=True)
    )


def main() -> None:
    here = Path(__file__).resolve().parent
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--tick-schedule", type=Path, default=here / "UPBIT_KRW_TICK_SCHEDULE_V1.json")
    p.add_argument("--parity-spec", type=Path, default=here / "BTC4H_CANONICAL_PARITY_V1.json")
    p.add_argument("--sleep-seconds", type=float, default=0.16)
    p.add_argument("--btc-parity-only", action="store_true")
    args = p.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    btc, btc_audit = fetch_binance_btc_4h()
    parity = verify_btc_parity(btc, btc_audit, args.parity_spec)
    parity_path = args.out_dir / "btc4h_public_parity_v1.json"
    parity_path.write_text(json.dumps(parity, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"btc_parity": parity["passed"], "rows": btc_audit["rows"], "sha256": btc_audit["sha256"]}, sort_keys=True))
    if args.btc_parity_only:
        return

    ticks = base.TickSchedule(args.tick_schedule)
    regimes = base.btc_regime_frame(btc)
    combined: list[pd.DataFrame] = []
    audit: dict[str, Any] = {
        "contract": "HARVEST_15M_REGIME_ASSET_CONTRACT_V1",
        "data_adapter": "PUBLIC_PARITY_GATED_V1",
        "window": [base.START_UTC.isoformat(), base.END_UTC.isoformat()],
        "btc_parity_sha256": btc_audit["sha256"],
        "tick_schedule_sha256": base.sha256_file(args.tick_schedule),
        "assets": {},
    }

    for symbol in base.UNIVERSE:
        candles = fetch_upbit_15m_robust(symbol, args.sleep_seconds)
        joined = base.join_causal(candles, regimes, ticks)
        path = args.out_dir / f"{symbol}_15m_regime_v1.csv"
        joined.to_csv(path, index=False, date_format="%Y-%m-%dT%H:%M:%S.%fZ", float_format="%.12g")
        item = base.audit_frame(joined)
        item["sha256"] = base.sha256_file(path)
        audit["assets"][symbol] = item
        combined.append(joined)
        print(json.dumps({"symbol": symbol, "rows": item.get("rows"), "first": item.get("first_open_time"), "last": item.get("last_open_time")}, sort_keys=True))

    all_rows = pd.concat(combined, ignore_index=True).sort_values(["open_time", "symbol"])
    combined_path = args.out_dir / "upbit_15m_regime_v1.csv"
    all_rows.to_csv(combined_path, index=False, date_format="%Y-%m-%dT%H:%M:%S.%fZ", float_format="%.12g")
    audit["combined_rows"] = int(len(all_rows))
    audit["combined_sha256"] = base.sha256_file(combined_path)
    audit_path = args.out_dir / "upbit_15m_regime_v1_audit.json"
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"combined_rows": audit["combined_rows"], "combined_sha256": audit["combined_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
