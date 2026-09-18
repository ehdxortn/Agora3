#!/usr/bin/env python3
"""One-shot evaluator for HARVEST 15M BOX-EDGE SHOCK REVERSION v1.

Applies the frozen rule without parameter search. Research-only; no production
or live-trading authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

START_UTC = pd.Timestamp("2025-01-01T00:00:00Z")
END_UTC = pd.Timestamp("2026-07-01T00:00:00Z")
UNIVERSE = ("ARB", "ENA", "NEAR", "POL", "ONDO", "SUI")
TP = 0.008
SL = 0.006
HOLD_BARS = 4
ROUND_TRIP_FEE_BPS = 10.0
BOOTSTRAP_SEED = 150919
BOOTSTRAP_SAMPLES = 10_000
BLOCK_DAYS = 7


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def max_drawdown(returns: np.ndarray) -> float | None:
    if len(returns) == 0:
        return None
    equity = np.cumprod(1.0 + returns)
    peak = np.maximum.accumulate(np.r_[1.0, equity])
    dd = np.r_[1.0, equity] / peak - 1.0
    return float(dd.min())


def metrics(trades: pd.DataFrame, column: str) -> dict[str, Any]:
    if trades.empty:
        return {"trades": 0}
    a = trades[column].to_numpy(dtype=float)
    pos = a[a > 0]
    neg = a[a <= 0]
    pf = None if neg.sum() == 0 else float(pos.sum() / abs(neg.sum()))
    return {
        "trades": int(len(a)),
        "mean_net_return": float(a.mean()),
        "median_net_return": float(np.median(a)),
        "win_rate": float((a > 0).mean()),
        "profit_factor": pf,
        "cumulative_return": float(np.prod(1.0 + a) - 1.0),
        "max_drawdown": max_drawdown(a),
    }


def daily_block_bootstrap_lb05(trades: pd.DataFrame, column: str) -> float | None:
    if trades.empty:
        return None
    daily = trades.assign(day=trades["entry_time"].dt.floor("D")).groupby("day", sort=True)[column].agg(list)
    days = daily.index.to_list()
    if len(days) < BLOCK_DAYS:
        return None
    values = [daily.loc[d] for d in days]
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    max_start = len(days) - BLOCK_DAYS
    blocks_needed = int(np.ceil(len(days) / BLOCK_DAYS))
    means = np.empty(BOOTSTRAP_SAMPLES, dtype=float)
    for i in range(BOOTSTRAP_SAMPLES):
        starts = rng.integers(0, max_start + 1, size=blocks_needed)
        sample: list[float] = []
        for start in starts:
            for j in range(start, min(start + BLOCK_DAYS, len(days))):
                sample.extend(values[j])
        means[i] = float(np.mean(sample)) if sample else np.nan
    means = means[np.isfinite(means)]
    return float(np.quantile(means, 0.05)) if len(means) else None


def prepare_asset(frame: pd.DataFrame) -> pd.DataFrame:
    f = frame.sort_values("open_time").copy().reset_index(drop=True)
    f["ret15"] = f["close"].pct_change()
    f["abs_ret15"] = f["ret15"].abs()
    f["box_low"] = f["low"].shift(1).rolling(16, min_periods=16).min()
    f["box_high"] = f["high"].shift(1).rolling(16, min_periods=16).max()
    f["median_abs_ret32"] = f["abs_ret15"].shift(1).rolling(32, min_periods=32).median()
    width = f["box_high"] - f["box_low"]
    f["box_position"] = (f["close"] - f["box_low"]) / width.replace(0, np.nan)
    common = (
        (width > 0)
        & (f["box_position"] <= 0.15)
        & (f["ret15"] < 0)
        & (f["abs_ret15"] >= f["median_abs_ret32"])
    ).fillna(False)
    f["primary_signal"] = common & (f["btc_regime"] != "STRONG_UP")
    f["strong_up_signal"] = common & (f["btc_regime"] == "STRONG_UP")
    return f


def simulate_asset(frame: pd.DataFrame, signal_col: str) -> list[dict[str, Any]]:
    f = frame.reset_index(drop=True)
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(f) - HOLD_BARS - 1:
        if not bool(f.at[i, signal_col]):
            i += 1
            continue
        entry_i = i + 1
        last_i = entry_i + HOLD_BARS - 1
        entry = float(f.at[entry_i, "open"])
        tick = float(f.at[entry_i, "tick_krw"])
        if not np.isfinite(entry) or entry <= 0 or not np.isfinite(tick) or tick <= 0:
            i += 1
            continue

        gross = None
        exit_i = last_i
        exit_reason = "TIME"
        for j in range(entry_i, last_i + 1):
            high = float(f.at[j, "high"])
            low = float(f.at[j, "low"])
            stop = low <= entry * (1.0 - SL)
            target = high >= entry * (1.0 + TP)
            if stop:  # conservative same-bar ordering
                gross = -SL
                exit_i = j
                exit_reason = "STOP"
                break
            if target:
                gross = TP
                exit_i = j
                exit_reason = "TARGET"
                break
        if gross is None:
            gross = float(f.at[last_i, "close"]) / entry - 1.0

        tick_bp = tick / entry * 10_000.0
        base_cost_bps = ROUND_TRIP_FEE_BPS + tick_bp
        stress_cost_bps = base_cost_bps + tick_bp
        path = f.loc[entry_i:last_i]
        mfe = float(path["high"].max() / entry - 1.0)
        mae = float(path["low"].min() / entry - 1.0)
        mfe_row = int(path["high"].idxmax())
        mae_row = int(path["low"].idxmin())

        out.append(
            {
                "symbol": str(f.at[i, "symbol"]),
                "signal_time": f.at[i, "decision_time"],
                "entry_time": f.at[entry_i, "open_time"],
                "exit_time": f.at[exit_i, "open_time"] + pd.Timedelta(minutes=15),
                "btc_regime": str(f.at[i, "btc_regime"]),
                "entry": entry,
                "tick_krw": tick,
                "tick_bp": tick_bp,
                "gross_return": gross,
                "base_cost_bps": base_cost_bps,
                "stress_cost_bps": stress_cost_bps,
                "net_return": gross - base_cost_bps / 10_000.0,
                "net_return_stress": gross - stress_cost_bps / 10_000.0,
                "exit_reason": exit_reason,
                "bars_held": int(exit_i - entry_i + 1),
                "mfe_60m": mfe,
                "mae_60m": mae,
                "bars_to_mfe": int(mfe_row - entry_i + 1),
                "bars_to_mae": int(mae_row - entry_i + 1),
                "mfe_mae_ratio": None if mae == 0 else float(mfe / abs(mae)),
            }
        )
        # Same-asset non-overlap: do not consider another signal until after exit.
        i = exit_i + 1
    return out


def evaluate(input_csv: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    f = pd.read_csv(input_csv)
    required = {
        "symbol", "open_time", "decision_time", "open", "high", "low", "close",
        "tick_krw", "btc_regime", "er24", "ret24",
    }
    missing = sorted(required - set(f.columns))
    if missing:
        raise ValueError(f"missing columns: {missing}")
    for c in ("open_time", "decision_time"):
        f[c] = pd.to_datetime(f[c], utc=True, format="mixed", errors="raise")
    for c in ("open", "high", "low", "close", "tick_krw", "er24", "ret24"):
        f[c] = pd.to_numeric(f[c], errors="raise")
    f = f[(f["open_time"] >= START_UTC) & (f["open_time"] < END_UTC)].copy()
    unexpected = sorted(set(f["symbol"]) - set(UNIVERSE))
    if unexpected:
        raise ValueError(f"unexpected symbols: {unexpected}")

    primary_rows: list[dict[str, Any]] = []
    strong_rows: list[dict[str, Any]] = []
    for _, group in f.groupby("symbol", sort=True):
        prepared = prepare_asset(group)
        primary_rows.extend(simulate_asset(prepared, "primary_signal"))
        strong_rows.extend(simulate_asset(prepared, "strong_up_signal"))

    trades = pd.DataFrame(primary_rows)
    strong = pd.DataFrame(strong_rows)
    for x in (trades, strong):
        if not x.empty:
            x["entry_time"] = pd.to_datetime(x["entry_time"], utc=True)
            x.sort_values(["entry_time", "symbol"], inplace=True)
            x.reset_index(drop=True, inplace=True)

    by_asset = {
        symbol: metrics(trades[trades["symbol"] == symbol], "net_return") if not trades.empty else {"trades": 0}
        for symbol in UNIVERSE
    }
    by_regime = {
        regime: metrics(trades[trades["btc_regime"] == regime], "net_return") if not trades.empty else {"trades": 0}
        for regime in ("RANGE", "TRANSITION", "STRONG_DOWN")
    }
    range_transition = trades[trades["btc_regime"].isin(["RANGE", "TRANSITION"])] if not trades.empty else trades

    split_time = None
    first = trades.iloc[0:0]
    second = trades.iloc[0:0]
    if not trades.empty:
        split_time = trades.iloc[len(trades) // 2]["entry_time"]
        first = trades[trades["entry_time"] < split_time]
        second = trades[trades["entry_time"] >= split_time]

    pooled = metrics(trades, "net_return")
    stress = metrics(trades, "net_return_stress")
    first_m = metrics(first, "net_return")
    second_m = metrics(second, "net_return")
    rt_m = metrics(range_transition, "net_return")
    sd_m = by_regime["STRONG_DOWN"]
    shares = trades["symbol"].value_counts(normalize=True).to_dict() if not trades.empty else {}
    qualifying = [s for s, m in by_asset.items() if m.get("trades", 0) >= 20]
    positive = [s for s in qualifying if (by_asset[s].get("mean_net_return") or 0.0) > 0]
    lb05 = daily_block_bootstrap_lb05(trades, "net_return") if not trades.empty else None

    gates = {
        "trades_ge_150": len(trades) >= 150,
        "four_assets_ge_20": len(qualifying) >= 4,
        "single_asset_share_le_40pct": max(shares.values(), default=0.0) <= 0.40,
        "pooled_mean_positive": (pooled.get("mean_net_return") or 0.0) > 0,
        "pooled_median_nonnegative": (pooled.get("median_net_return") if pooled.get("median_net_return") is not None else -1.0) >= 0,
        "bootstrap_lb05_positive": lb05 is not None and lb05 > 0,
        "first_half_mean_positive": (first_m.get("mean_net_return") or 0.0) > 0,
        "second_half_mean_positive": (second_m.get("mean_net_return") or 0.0) > 0,
        "four_of_six_assets_positive": len(positive) >= 4,
        "one_extra_tick_stress_nonnegative": (stress.get("mean_net_return") if stress.get("mean_net_return") is not None else -1.0) >= 0,
        "strong_down_not_below_minus15bp_if_n30": sd_m.get("trades", 0) < 30 or (sd_m.get("mean_net_return") or -1.0) > -0.0015,
        "range_transition_not_below_minus15bp_if_n30": rt_m.get("trades", 0) < 30 or (rt_m.get("mean_net_return") or -1.0) > -0.0015,
    }

    result = {
        "contract": "HARVEST_15M_REGIME_ASSET_CONTRACT_V1",
        "rule": "BOX_EDGE_SHOCK_REVERSION_V1",
        "input_sha256": sha256_file(input_csv),
        "interval": [START_UTC.isoformat(), END_UTC.isoformat()],
        "execution": {
            "round_trip_fee_bps": ROUND_TRIP_FEE_BPS,
            "spread_proxy": "one date-correct tick",
            "stress": "one additional date-correct tick",
            "take_profit": TP,
            "stop_loss": SL,
            "max_hold_bars": HOLD_BARS,
            "same_bar_order": "STOP_FIRST",
        },
        "pooled": pooled,
        "stress": stress,
        "by_asset": by_asset,
        "by_regime": by_regime,
        "range_plus_transition": rt_m,
        "first_half": first_m,
        "second_half": second_m,
        "chronological_split_time": None if split_time is None else split_time.isoformat(),
        "asset_shares": shares,
        "qualifying_assets_ge20": qualifying,
        "positive_qualifying_assets": positive,
        "daily_block_bootstrap": {
            "seed": BOOTSTRAP_SEED,
            "samples": BOOTSTRAP_SAMPLES,
            "block_days": BLOCK_DAYS,
            "lb05_mean_net_return": lb05,
        },
        "gate_checks": gates,
        "passed_all_primary_gates": all(gates.values()),
        "strong_up_diagnostic": metrics(strong, "net_return"),
    }
    return result, trades


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--trades-output", type=Path, required=True)
    args = p.parse_args()
    result, trades = evaluate(args.input)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    trades.to_csv(args.trades_output, index=False, float_format="%.12g")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
