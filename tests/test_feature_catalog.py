import pytest
from pydantic import ValidationError

from research_engine.models import FeatureSpec


def test_onchain_feature_rejects_unloaded_exchange_reserve_column():
    with pytest.raises(ValidationError):
        FeatureSpec(
            name="reserve_z",
            family="onchain_zscore",
            lookback=180,
            column="exchange_reserve_change",
        )


def test_onchain_feature_accepts_loaded_active_addresses():
    spec = FeatureSpec(
        name="active_z",
        family="onchain_zscore",
        lookback=30,
        column="active_addresses",
    )
    assert spec.column == "active_addresses"


def test_oi_feature_rejects_unknown_column():
    with pytest.raises(ValidationError):
        FeatureSpec(name="oi_z", family="oi_zscore", lookback=24, column="liquidations")


def test_data_backed_feature_defaults_remain_valid():
    assert FeatureSpec(name="oi", family="oi_zscore", lookback=24).column is None
    assert FeatureSpec(name="flow", family="taker_imbalance", lookback=3).column is None
    assert FeatureSpec(name="chain", family="onchain_zscore", lookback=30).column is None
