from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load_module("harvest_builder", ROOT / "research" / "harvest_15m_builder_v1.py")
evaluator = load_module("harvest_eval", ROOT / "research" / "harvest_15m_evaluator_v1.py")


def test_tick_schedule_pol_override_and_marketwide_change():
    schedule = builder.TickSchedule(ROOT / "research" / "UPBIT_KRW_TICK_SCHEDULE_V1.json")
    assert schedule.tick("POL", "2024-10-13T14:59:00Z", 200.0) == 0.1
    assert schedule.tick("POL", "2024-10-14T00:00:00Z", 200.0) == 1.0
    assert schedule.tick("ARB", "2024-10-14T00:00:00Z", 200.0) == 0.1
    assert schedule.tick("ARB", "2025-07-30T17:00:00Z", 200.0) == 1.0


def test_btc_regime_is_known_only_after_completed_4h_bar():
    start = pd.Timestamp("2025-01-01T00:00:00Z")
    rows = []
    for i in range(8):
        rows.append(
            {
                "open_time": start + pd.Timedelta(hours=4 * i),
                "open": 100 + i,
                "high": 101 + i,
                "low": 99 + i,
                "close": 100 + i,
                "volume": 1,
            }
        )
    regime = builder.btc_regime_frame(pd.DataFrame(rows))
    # First 24h ER uses closes t and t-6, so it becomes usable only at the
    # close of the seventh 4H bar: open 24h, decision 28h.
    assert regime.iloc[0]["btc_decision_time"] == start + pd.Timedelta(hours=28)


def synthetic_asset_frame() -> pd.DataFrame:
    start = pd.Timestamp("2025-01-01T00:00:00Z")
    rows = []
    for i in range(40):
        rows.append(
            {
                "symbol": "ARB",
                "open_time": start + pd.Timedelta(minutes=15 * i),
                "decision_time": start + pd.Timedelta(minutes=15 * (i + 1)),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "tick_krw": 0.1,
                "btc_regime": "RANGE",
                "er24": 0.1,
                "ret24": 0.0,
            }
        )
    # Prior 16-bar box is [99,101]. Signal closes at its bottom after a
    # negative move. Next bar opens at 99 and touches both SL and TP, so the
    # conservative STOP_FIRST rule must win.
    rows[35].update(open=100.0, high=100.0, low=99.0, close=99.0)
    rows[36].update(open=99.0, high=100.0, low=98.0, close=99.5)
    return pd.DataFrame(rows)


def test_signal_uses_prior_box_and_stop_first():
    f = evaluator.prepare_asset(synthetic_asset_frame())
    assert bool(f.at[35, "primary_signal"])
    trades = evaluator.simulate_asset(f, "primary_signal")
    assert trades
    assert trades[0]["exit_reason"] == "STOP"
    assert abs(trades[0]["gross_return"] + evaluator.SL) < 1e-12


def test_cost_model_includes_fee_tick_and_extra_tick_stress():
    f = evaluator.prepare_asset(synthetic_asset_frame())
    trade = evaluator.simulate_asset(f, "primary_signal")[0]
    tick_bp = 0.1 / 99.0 * 10_000.0
    assert abs(trade["tick_bp"] - tick_bp) < 1e-9
    assert abs(trade["base_cost_bps"] - (10.0 + tick_bp)) < 1e-9
    assert abs(trade["stress_cost_bps"] - (10.0 + 2 * tick_bp)) < 1e-9


def test_same_asset_positions_do_not_overlap():
    f = evaluator.prepare_asset(synthetic_asset_frame())
    f.loc[:, "primary_signal"] = False
    f.at[35, "primary_signal"] = True
    f.at[36, "primary_signal"] = True
    f.at[37, "primary_signal"] = True
    trades = evaluator.simulate_asset(f, "primary_signal")
    assert len(trades) == 1
