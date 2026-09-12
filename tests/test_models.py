import pytest
from pydantic import ValidationError
from research_engine.models import ConditionSpec,ExperimentSpec,FeatureSpec

def test_quantile_bounds():
 with pytest.raises(ValidationError):ConditionSpec(feature="x",op="gt",threshold_type="train_quantile",value=1.2)
def test_condition_reference():
 with pytest.raises(ValidationError):ExperimentSpec(hypothesis="A sufficiently detailed hypothesis for schema testing.",mechanism="A sufficiently detailed causal mechanism for schema testing.",side="long",features=[FeatureSpec(name="a",family="rsi",lookback=14)],conditions=[ConditionSpec(feature="b",op="gt",value=50)])
