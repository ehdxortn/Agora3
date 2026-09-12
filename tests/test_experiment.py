import numpy as np,pandas as pd
from research_engine.experiment import ExperimentRunner
from research_engine.models import ConditionSpec,ExitSpec,ExperimentSpec,FeatureSpec

def data(n=3200):
 r=np.random.default_rng(7);t=pd.date_range("2022-01-01",periods=n,freq="4h",tz="UTC");x=r.normal(0,.004,n)
 for i in range(5,n-1):
  if x[i-3:i].sum()>.012:x[i+1]+=.003
 c=30000*np.exp(np.cumsum(x));o=np.r_[c[0],c[:-1]];h=np.maximum(o,c)*(1+r.uniform(.0005,.004,n));l=np.minimum(o,c)*(1-r.uniform(.0005,.004,n));return pd.DataFrame({"open_time":t,"decision_time":t+pd.Timedelta(hours=4),"open":o,"high":h,"low":l,"close":c,"volume":r.lognormal(10,.4,n)})
def test_runner():
 s=ExperimentSpec(hypothesis="Strong recent momentum may continue into the next twelve hours after costs.",mechanism="Information diffusion may produce short-lived continuation after unusually strong returns.",side="long",features=[FeatureSpec(name="mom3",family="price_return",lookback=3)],conditions=[ConditionSpec(feature="mom3",op="gt",threshold_type="train_quantile",value=.8)],exit=ExitSpec(mode="fixed_horizon",horizon_bars=3));r=ExperimentRunner(data()).run(s);assert r.train.trades>0 and r.test.observations>0
def test_stop_first():
 d=data(800);d["high"]=d.open*1.1;d["low"]=d.open*.9;s=ExperimentSpec(hypothesis="Synthetic test validates conservative same-bar stop and target handling.",mechanism="Unknown intrabar ordering must assume the adverse stop occurs first.",side="long",features=[FeatureSpec(name="mom1",family="price_return",lookback=1)],conditions=[ConditionSpec(feature="mom1",op="gt",threshold_type="train_quantile",value=.5)],exit=ExitSpec(mode="stop_target",horizon_bars=3,stop_loss_pct=.02,take_profit_pct=.02),fee_bps=0,slippage_bps=0);r=ExperimentRunner(d).run(s,False);assert r.train.mean_net_return<=0
