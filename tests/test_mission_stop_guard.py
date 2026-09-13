from research_engine.models import Confidence, DirectorDecision
from research_engine.orchestrator import _decision_requests_global_stop, _premature_global_stop


def decision(status="CONTINUE", action="EXPERIMENT"):
    return DirectorDecision(
        research_status=status,
        confidence=Confidence.WEAK,
        interpretation="test",
        critic_questions=[],
        research_directive="continue research",
        next_action=action,
        next_experiment=None,
        reason_for_next_action="test",
    )


def test_stop_detection_accepts_complete_or_stop():
    assert _decision_requests_global_stop(decision(status="COMPLETE", action="EXPERIMENT"))
    assert _decision_requests_global_stop(decision(status="CONTINUE", action="STOP"))
    assert not _decision_requests_global_stop(decision())
    assert _decision_requests_global_stop({"research_status": "COMPLETE", "next_action": "STOP"})


def test_premature_stop_requires_budget_no_promotion_and_insufficient_breadth():
    assert _premature_global_stop(
        experiment_count=5,
        promotion_count=0,
        remaining_budget=6.9,
        minimum_experiments=12,
    )
    assert not _premature_global_stop(
        experiment_count=12,
        promotion_count=0,
        remaining_budget=6.9,
        minimum_experiments=12,
    )
    assert not _premature_global_stop(
        experiment_count=5,
        promotion_count=1,
        remaining_budget=6.9,
        minimum_experiments=12,
    )
    assert not _premature_global_stop(
        experiment_count=5,
        promotion_count=0,
        remaining_budget=0.25,
        minimum_experiments=12,
    )
