import numpy as np,pandas as pd
from research_engine.experiment import ExperimentRunner
from research_engine.models import ConditionSpec,ExperimentSpec,FeatureSpec

def data(n=3000):
 r=np.random.default_rng(11);t=pd.date_range('2021-01-01',periods=n,freq='4h',tz='UTC');x=r.normal(0,.005,n);c=30000*np.exp(np.cumsum(x));o=np.r_[c[0],c[:-1]];h=np.maximum(o,c)*1.002;l=np.minimum(o,c)*.998;return pd.DataFrame({'open_time':t,'decision_time':t+pd.Timedelta(hours=4),'open':o,'high':h,'low':l,'close':c,'volume':1.0})
def spec():return ExperimentSpec(hypothesis='Recent positive return may condition the next several bars under a momentum mechanism.',mechanism='Short-horizon information diffusion can generate temporary autocorrelation that is falsifiable.',side='long',features=[FeatureSpec(name='m',family='price_return',lookback=3)],conditions=[ConditionSpec(feature='m',op='gt',threshold_type='train_quantile',value=.5)])
def test_holdout_is_sealed_by_default():
 r=ExperimentRunner(data()).run(spec(),stability=False);assert r.holdout_revealed is False;assert r.gate_basis=='validation';assert r.test.trades==0
def test_holdout_can_be_revealed_explicitly():
 a=ExperimentRunner(data());r=a.run(spec(),stability=False);x=a.run(spec(),stability=False,reveal_holdout=True,experiment_id=r.experiment_id);assert x.holdout_revealed is True;assert x.gate_basis=='test';assert x.experiment_id==r.experiment_id
