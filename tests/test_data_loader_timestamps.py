import asyncio

import pandas as pd

from research_engine.experiment import BTCDataLoader


class FakeDB:
    async def paged_select(self, table, columns="*", page_size=1000, order=None, **eq):
        if table == "candles_4h":
            return [
                {"symbol": "BTC", "open_time": "2026-08-23T12:00:00+00:00", "open": "100", "high": "102", "low": "99", "close": "101", "volume": "10"},
                {"symbol": "BTC", "open_time": "2026-08-23T16:00:00.006+00:00", "open": "101", "high": "103", "low": "100", "close": "102", "volume": "11"},
                {"symbol": "BTC", "open_time": "2026-08-23T20:00:00Z", "open": "102", "high": "104", "low": "101", "close": "103", "volume": "12"},
            ]
        if table == "btc_futures_metrics_4h":
            return [
                {"symbol": "BTCUSDT", "bucket_open": "2026-08-23T12:00:00+00:00", "oi_close": "1", "oi_value_close": "1", "toptrader_account_ls_close": "1", "toptrader_position_ls_close": "1", "global_account_ls_close": "1", "taker_ls_close": "1", "taker_log_imbalance_mean": "0.1", "missing_slots": 0, "conflicting_duplicate_rows": 0},
                {"symbol": "BTCUSDT", "bucket_open": "2026-08-23T16:00:00.006+00:00", "oi_close": "2", "oi_value_close": "2", "toptrader_account_ls_close": "1", "toptrader_position_ls_close": "1", "global_account_ls_close": "1", "taker_ls_close": "1", "taker_log_imbalance_mean": "0.2", "missing_slots": 0, "conflicting_duplicate_rows": 0},
            ]
        if table == "funding_rates":
            return [
                {"symbol": "BTC", "funding_time": "2026-08-23T08:00:00+00:00", "funding_rate": "0.0001", "mark_price": "100"},
                {"symbol": "BTC", "funding_time": "2026-08-23T16:00:00.006+00:00", "funding_rate": "0.0002", "mark_price": "102"},
            ]
        if table == "btc_onchain_daily_raw":
            return [
                {"day": "2026-08-20", "tx_count": "1", "block_count": "1", "fees_btc": "1", "gross_output_btc": "1", "mean_fee_sat_vb": "1", "median_fee_sat_vb": "1", "active_addresses": "1", "hash_rate": "1"}
            ]
        return []


def test_loader_accepts_mixed_iso8601_precision():
    df = asyncio.run(BTCDataLoader(FakeDB()).load())
    assert len(df) == 3
    assert str(df["open_time"].dtype) == "datetime64[ns, UTC]"
    assert str(df["funding_time"].dtype) == "datetime64[ns, UTC]"
    assert pd.notna(df.loc[1, "funding_rate"])
    assert df["open_time"].is_monotonic_increasing


def test_normalize_time_drops_only_unparseable_rows():
    frame = pd.DataFrame({"t": ["2026-08-23T16:00:00.006+00:00", "bad", "2026-08-23T20:00:00Z"]})
    normalized, dropped = BTCDataLoader._normalize_time(frame, "t", "fixture")
    assert dropped == 1
    assert len(normalized) == 2
    assert normalized["t"].notna().all()
