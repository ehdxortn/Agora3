from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = ROOT / "research" / "personal_trade_style_analyzer_v0.py"
    spec = importlib.util.spec_from_file_location("personal_trade_style_analyzer_v0", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


m = load_module()


def test_exact_round_trip_uses_reported_fees():
    orders = pd.DataFrame(
        [
            {
                "order_time": pd.Timestamp("2026-01-01 00:00"),
                "symbol": "ARB",
                "action": "매수",
                "price": 100.0,
                "qty": 1000.0,
                "gross": 100000.0,
                "fee": 50.0,
                "net": 100050.0,
                "fill_count": 2,
                "first_fill": pd.Timestamp("2026-01-01 00:01"),
                "last_fill": pd.Timestamp("2026-01-01 00:02"),
            },
            {
                "order_time": pd.Timestamp("2026-01-01 00:20"),
                "symbol": "ARB",
                "action": "매도",
                "price": 101.0,
                "qty": 1000.0,
                "gross": 101000.0,
                "fee": 50.5,
                "net": 100949.5,
                "fill_count": 1,
                "first_fill": pd.Timestamp("2026-01-01 00:21"),
                "last_fill": pd.Timestamp("2026-01-01 00:21"),
            },
        ]
    )
    trips = m.exact_round_trips(orders)
    assert len(trips) == 1
    assert abs(trips.iloc[0]["pnl"] - 899.5) < 1e-12
    assert trips.iloc[0]["fill_to_fill_minutes"] == 19.0


def test_mixed_inventory_is_not_forced_into_round_trip():
    orders = pd.DataFrame(
        [
            {
                "order_time": pd.Timestamp("2026-01-01 00:00"),
                "symbol": "ARB",
                "action": "매수",
                "price": 100.0,
                "qty": 1000.0,
                "gross": 100000.0,
                "fee": 50.0,
                "net": 100050.0,
                "fill_count": 1,
                "first_fill": pd.Timestamp("2026-01-01 00:00"),
                "last_fill": pd.Timestamp("2026-01-01 00:00"),
            },
            {
                "order_time": pd.Timestamp("2026-01-01 01:00"),
                "symbol": "ARB",
                "action": "매도",
                "price": 101.0,
                "qty": 1500.0,
                "gross": 151500.0,
                "fee": 75.75,
                "net": 151424.25,
                "fill_count": 1,
                "first_fill": pd.Timestamp("2026-01-01 01:00"),
                "last_fill": pd.Timestamp("2026-01-01 01:00"),
            },
        ]
    )
    assert m.exact_round_trips(orders).empty
