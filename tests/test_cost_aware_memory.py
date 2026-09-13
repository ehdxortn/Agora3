from research_engine.literature import LiteratureResearcher, _compact_failure, _record_score


def test_retrieval_score_prefers_relevant_high_quality_source():
    relevant = {
        "title": "Bitcoin funding rate and open interest predict deleveraging",
        "topic": "BTC perpetual futures funding rate and subsequent returns",
        "tags": ["funding", "open-interest", "deleveraging"],
        "research_question": "Does crowded derivatives positioning predict reversals?",
        "claim": "Extreme funding with open-interest stress precedes reversals.",
        "method": "chronological backtest",
        "quality_tier": "A",
        "replication_value": "HIGH",
    }
    unrelated = {
        "title": "Bitcoin active addresses",
        "topic": "BTC on-chain activity",
        "tags": ["onchain"],
        "research_question": "Do active addresses predict long horizon returns?",
        "claim": "Mixed evidence.",
        "method": "regression",
        "quality_tier": "A",
        "replication_value": "HIGH",
    }
    query = "funding open interest deleveraging reversal"
    assert _record_score(relevant, query) > _record_score(unrelated, query)


def test_failure_memory_is_compacted_before_llm_context():
    row = {
        "spec_hash": "abc",
        "hypothesis": "Funding extremes may reverse.",
        "status": "REJECTED",
        "rejection_reason": "x" * 5000,
        "spec": {
            "side": "short",
            "features": [{"family": "funding_zscore", "lookback": 42, "name": "f"}],
            "conditions": [{"feature": "f", "op": "gt", "threshold_type": "train_quantile", "value": 0.9}],
            "exit": {"mode": "fixed_horizon", "horizon_bars": 3},
        },
        "result": {
            "train": {"trades": 100, "mean_net_return": -0.001, "profit_factor": 0.9, "max_drawdown": -0.2},
            "validation": {"trades": 40, "mean_net_return": -0.002, "profit_factor": 0.8, "max_drawdown": -0.1},
            "parity_fixture": {"huge": "payload"},
        },
    }
    compact = _compact_failure(row)
    assert len(compact["rejection_reason"]) == 1000
    assert "parity_fixture" not in compact
    assert compact["validation"]["trades"] == 40


def test_relevant_failure_selection_uses_query_not_full_history():
    researcher = LiteratureResearcher(None, None, None)
    rows = [
        {
            "spec_hash": "funding",
            "hypothesis": "Funding and open interest crowding predicts reversal",
            "status": "REJECTED",
            "rejection_reason": "funding edge failed validation",
            "spec": {"features": [{"family": "funding_zscore"}, {"family": "oi_change"}]},
            "result": {},
        },
        {
            "spec_hash": "onchain",
            "hypothesis": "Active addresses predict returns",
            "status": "REJECTED",
            "rejection_reason": "onchain edge failed",
            "spec": {"features": [{"family": "onchain_zscore"}]},
            "result": {},
        },
    ]
    selected = researcher.relevant_failures(rows, "funding open interest derivatives")
    assert selected[0]["spec_hash"] == "funding"
