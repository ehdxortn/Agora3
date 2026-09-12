from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from research_engine.models import CriticReview, LiteratureBatch, LiteratureItem, LiteratureMap


def test_vendor_sdks_expose_structured_parse_helpers():
    anthropic = AsyncAnthropic(api_key="test-key")
    openai = AsyncOpenAI(api_key="test-key")
    assert hasattr(anthropic.messages, "parse")
    assert hasattr(openai.responses, "parse")


def test_literature_batch_contract_normalizes_legacy_fields():
    batch = LiteratureBatch.model_validate(
        {
            "items": [
                {
                    "title": "Example",
                    "url": "https://example.com/paper",
                    "source_type": "other",
                    "quality_tier": "B",
                    "published_date": None,
                    "research_question": "Does the signal predict BTC returns?",
                    "claim": "Example claim",
                    "method": "Chronological test",
                    "dataset_period": "2020-2025",
                    "timeframe": "4h",
                    "costs_included": "not reported",
                    "leakage_risks": "Potential revised-data timing risk",
                    "replication_value": "MEDIUM",
                    "tags": "momentum",
                }
            ]
        }
    )
    item = batch.items[0]
    assert item.costs_included is None
    assert item.leakage_risks == ["Potential revised-data timing risk"]
    assert item.tags == ["momentum"]


def test_literature_map_and_critic_contracts():
    research_map = LiteratureMap(
        themes=["momentum"],
        replicated_findings=["mixed persistence"],
        contradictions=[],
        weak_or_invalid_claims=[],
        high_value_replications=["cost-aware 4h replication"],
        open_questions=["regime dependence"],
    )
    assert research_map.themes == ["momentum"]

    review = CriticReview(
        verdict="CHALLENGE",
        fatal_objections=["timestamp uncertainty"],
        nonfatal_objections=[],
        required_tests=["verify publication lag"],
        assessment="Holdout must remain sealed until timing is verified.",
    )
    assert review.verdict == "CHALLENGE"


def test_literature_item_still_accepts_strict_values():
    item = LiteratureItem(
        title="Strict",
        url="https://example.org",
        source_type="institutional",
        quality_tier="A",
        research_question="Question",
        claim="Claim",
        method="Method",
        costs_included=True,
        leakage_risks=["none identified"],
        tags=["btc"],
    )
    assert item.costs_included is True
