from __future__ import annotations
import hashlib,math
from typing import Any,TYPE_CHECKING
from uuid import uuid4
import numpy as np
import pandas as pd
from .config import settings
from .models import ConditionSpec,ExperimentResult,ExperimentSpec,FeatureSpec,SplitMetrics
if TYPE_CHECKING:
 from .db import ResearchDB

class BTCDataLoader:
 def __init__(self,db:"ResearchDB"):self.db=db
 async def load(self):
  candles,futures,funding,onchain=await self._load_sources()
  if not candles:raise RuntimeError("candles_4h contains no BTC rows")
  df=pd.DataFrame(candles)
  for c in ["open","high","low","close","volume"]:df[c]=pd.to_numeric(df[c],errors="coerce")
  df["open_time"]=pd.to_datetime(df["open_time"],utc=True);df=df.sort_values("open_time").drop_duplicates("open_time",keep="last");df["decision_time"]=df["open_time"]+pd.Timedelta(hours=4)
  if futures:
   f=pd.DataFrame(futures);f["bucket_open"]=pd.to_datetime(f["bucket_open"],utc=True)
   numeric=[c for c in f.columns if c not in {"symbol","bucket_open"}]
   for c in numeric:f[c]=pd.to_numeric(f[c],errors="coerce")
   bad=(f.get("missing_slots",0).fillna(0)>0)|(f.get("conflicting_duplicate_rows",0).fillna(0)>0)
   signal_cols=[c for c in f.columns if c not in {"symbol","bucket_open","missing_slots","conflicting_duplicate_rows"}]
   f.loc[bad,signal_cols]=np.nan;f=f.sort_values("bucket_open").drop_duplicates("bucket_open",keep="last");df=df.merge(f.drop(columns=["symbol"],errors="ignore"),left_on="open_time",right_on="bucket_open",how="left")
  if funding:
   f=pd.DataFrame(funding);f["funding_time"]=pd.to_datetime(f["funding_time"],utc=True);f["funding_rate"]=pd.to_numeric(f["funding_rate"],errors="coerce");f=f.sort_values("funding_time").drop_duplicates("funding_time",keep="last");df=pd.merge_asof(df.sort_values("decision_time"),f[["funding_time","funding_rate"]],left_on="decision_time",right_on="funding_time",direction="backward",allow_exact_matches=True)
  if onchain:
   o=pd.DataFrame(onchain);o["day"]=pd.to_datetime(o["day"],utc=True)
   for c in o.columns:
    if c!="day":o[c]=pd.to_numeric(o[c],errors="coerce")
   o["available_at"]=o["day"]+pd.Timedelta(days=settings.onchain_lag_days);keep=[c for c in o.columns if c!="day"]
   df=pd.merge_asof(df.sort_values("decision_time"),o[keep].sort_values("available_at"),left_on="decision_time",right_on="available_at",direction="backward",allow_exact_matches=True,suffixes=("","_onchain"))
  return df.sort_values("open_time").reset_index(drop=True)
 async def _load_sources(self):
  import asyncio
  return await asyncio.gather(self.db.paged_select("candles_4h","symbol,open_time,open,high,low,close,volume",order="open_time",symbol="BTC"),self.db.paged_select("btc_futures_metrics_4h","symbol,bucket_open,oi_close,oi_value_close,toptrader_account_ls_close,toptrader_position_ls_close,global_account_ls_close,taker_ls_close,taker_log_imbalance_mean,missing_slots,conflicting_duplicate_rows",order="bucket_open",symbol="BTCUSDT"),self.db.paged_select("funding_rates","symbol,funding_time,funding_rate,mark_price",order="funding_time",symbol="BTC"),self.db.paged_select("btc_onchain_daily_raw","day,tx_count,block_count,fees_btc,gross_output_btc,mean_fee_sat_vb,median_fee_sat_vb,active_addresses,hash_rate",order="day"))

class FeatureEngine:
 @staticmethod
 def z(s,n):
  m=s.rolling(n,min_periods=n).mean();sd=s.rolling(n,min_periods=n).std(ddof=1).replace(0,np.nan);return (s-m)/sd
 @staticmethod
 def req(df,col,f):
  if col not in df.columns:raise ValueError(f"Feature {f.name} requires missing column {col}")
 def apply(self,df,features):
  out=df.copy();lr=np.log(out.close/out.close.shift(1));tr=pd.concat([out.high-out.low,(out.high-out.close.shift(1)).abs(),(out.low-out.close.shift(1)).abs()],axis=1).max(axis=1)
  for f in features:
   if f.family=="price_return":out[f.name]=out.close.pct_change(f.lookback)
   elif f.family=="ema_gap":
    fast=f.fast or max(2,f.lookback//2);slow=f.slow or f.lookback
    if fast>=slow:raise ValueError("ema fast must be < slow")
    out[f.name]=out.close.ewm(span=fast,adjust=False,min_periods=fast).mean()/out.close.ewm(span=slow,adjust=False,min_periods=slow).mean()-1
   elif f.family=="rsi":
    d=out.close.diff();g=d.clip(lower=0).rolling(f.lookback,min_periods=f.lookback).mean();l=(-d.clip(upper=0)).rolling(f.lookback,min_periods=f.lookback).mean();rs=g/l.replace(0,np.nan);out[f.name]=100-100/(1+rs)
   elif f.family=="atr_pct":out[f.name]=tr.rolling(f.lookback,min_periods=f.lookback).mean()/out.close
   elif f.family=="realized_vol":out[f.name]=lr.rolling(f.lookback,min_periods=f.lookback).std(ddof=1)*math.sqrt(f.lookback)
   elif f.family=="volume_zscore":out[f.name]=self.z(out.volume,f.lookback)
   elif f.family in {"oi_change","oi_zscore"}:
    col=f.column or "oi_value_close";self.req(out,col,f);out[f.name]=out[col].pct_change(f.lookback) if f.family=="oi_change" else self.z(out[col],f.lookback)
   elif f.family in {"funding_mean","funding_zscore"}:
    self.req(out,"funding_rate",f);out[f.name]=out.funding_rate.rolling(f.lookback,min_periods=f.lookback).mean() if f.family=="funding_mean" else self.z(out.funding_rate,f.lookback)
   elif f.family=="taker_imbalance":
    col=f.column or "taker_log_imbalance_mean";self.req(out,col,f);out[f.name]=out[col].rolling(f.lookback,min_periods=max(1,min(f.lookback,3))).mean()
   elif f.family=="ls_ratio_zscore":
    col=f.column or "global_account_ls_close";self.req(out,col,f);out[f.name]=self.z(out[col],f.lookback)
   elif f.family=="onchain_zscore":
    col=f.column or "active_addresses";self.req(out,col,f);out[f.name]=self.z(out[col],max(6,f.lookback*6))
   else:raise ValueError(f"Unsupported feature family {f.family}")
  return out

class ExperimentRunner:
 def __init__(self,data):self.raw=data;self.feature_engine=FeatureEngine()
 def run(self,spec,stability=True,reveal_holdout=False,experiment_id=None):
  sh=hashlib.sha256(spec.model_dump_json().encode()).hexdigest();eid=experiment_id or f"EXP-{uuid4().hex[:12]}";df=self.feature_engine.apply(self.raw,spec.features);names=[f.name for f in spec.features];u=df.dropna(subset=names+["open","high","low","close"]).reset_index(drop=True)
  if len(u)<400:raise ValueError(f"Insufficient usable observations: {len(u)}")
  n=len(u);te=int(n*spec.train_fraction);ve=int(n*(spec.train_fraction+spec.validation_fraction));e=spec.embargo_bars;slices=[(0,max(0,te-e)),(min(n,te+e),max(min(n,ve-e),min(n,te+e))),(min(n,ve+e),n)]
  if min(b-a for a,b in slices)<=20:raise ValueError("split/embargo leaves too little data")
  th=self._resolve_thresholds(u.iloc[slices[0][0]:slices[0][1]],spec.conditions);sig=self._build_signal(u,spec.conditions,th);analysis_end=n if reveal_holdout else slices[2][0];allr=self._simulate(u.iloc[:analysis_end].reset_index(drop=True),sig.iloc[:analysis_end].reset_index(drop=True),spec);tr=self._returns_for_range(allr,*slices[0]);vr=self._returns_for_range(allr,*slices[1]);xr=self._returns_for_range(allr,*slices[2]) if reveal_holdout else []
  flags=[] if reveal_holdout else ["SEALED_HOLDOUT_NOT_EVALUATED"]
  if reveal_holdout and len(xr)<30:flags.append("LOW_OOS_SAMPLE")
  if reveal_holdout and tr and xr and np.mean(tr)>0>=np.mean(xr):flags.append("OOS_SIGN_FLIP")
  if reveal_holdout and vr and xr and np.mean(vr)*np.mean(xr)<0:flags.append("VALIDATION_TEST_INSTABILITY")
  r=ExperimentResult(experiment_id=eid,spec_hash=sh,train=self._metrics(tr,slices[0][1]-slices[0][0]),validation=self._metrics(vr,slices[1][1]-slices[1][0]),test=self._metrics(xr,slices[2][1]-slices[2][0]),methodological_flags=flags,holdout_revealed=reveal_holdout,gate_basis="test" if reveal_holdout else "validation")
  if stability:r.parameter_stability=self._stability_sweep(spec,reveal_holdout)
  r.passed_minimum_gate=self._minimum_gate(r,"test" if reveal_holdout else "validation");return r
 def _resolve_thresholds(self,train,conds):return {i:(float(c.value) if c.threshold_type=="absolute" else float(train[c.feature].quantile(c.value))) for i,c in enumerate(conds)}
 @staticmethod
 def _build_signal(df,conds,th):
  s=pd.Series(True,index=df.index)
  for i,c in enumerate(conds):
   x=df[c.feature];t=th[i]
   if c.op=="gt":s&=x>t
   elif c.op=="gte":s&=x>=t
   elif c.op=="lt":s&=x<t
   else:s&=x<=t
  return s.fillna(False)
 def _simulate(self,df,signal,spec):
  out=[];i=0;cost=(spec.fee_bps+spec.slippage_bps)/10000
  while i<len(df)-2:
   if not bool(signal.iloc[i]):i+=1;continue
   ei=i+1;entry=float(df.iloc[ei].open)
   if not np.isfinite(entry) or entry<=0:i+=1;continue
   mx=min(len(df)-1,ei+spec.exit.horizon_bars-1);gross=None;xi=mx
   if spec.exit.mode=="stop_target":
    sl=float(spec.exit.stop_loss_pct or 0);tp=float(spec.exit.take_profit_pct or 0)
    for j in range(ei,mx+1):
     h=float(df.iloc[j].high);l=float(df.iloc[j].low);stop=(l<=entry*(1-sl)) if spec.side=="long" else (h>=entry*(1+sl));target=(h>=entry*(1+tp)) if spec.side=="long" else (l<=entry*(1-tp))
     if stop:gross,xi=-sl,j;break
     if target:gross,xi=tp,j;break
   if gross is None:
    raw=float(df.iloc[mx].close)/entry-1;gross=raw if spec.side=="long" else -raw
   out.append((i,xi,float(gross-cost)));i=max(i+1,xi+1)
  return out
 @staticmethod
 def _returns_for_range(allr,a,b):return [r for i,x,r in allr if a<=i<b and x<b]
 @staticmethod
 def _metrics(rs,obs):
  if not rs:return SplitMetrics(observations=obs,trades=0)
  a=np.asarray(rs,float);w=a[a>0];l=a[a<=0];eq=np.cumprod(1+a);dd=eq/np.maximum.accumulate(eq)-1;pf=float(w.sum()/abs(l.sum())) if l.sum()<0 else None;sd=float(a.std(ddof=1)) if len(a)>1 else 0
  return SplitMetrics(observations=obs,trades=len(a),win_rate=float((a>0).mean()),mean_net_return=float(a.mean()),median_net_return=float(np.median(a)),profit_factor=pf,max_drawdown=float(dd.min()),cumulative_return=float(eq[-1]-1),sharpe_like=float(a.mean()/sd*math.sqrt(len(a))) if sd>0 else None)
 def _stability_sweep(self,spec,reveal):
  vs=[];key="test" if reveal else "validation"
  for d in (-.05,.05):
   c=spec.model_copy(deep=True);changed=False
   for x in c.conditions:
    if x.threshold_type=="train_quantile":x.value=min(.95,max(.05,x.value+d));changed=True
   if not changed:
    for x in c.conditions:
     if x.value!=0:x.value*=1+d;changed=True
   if changed:
    try:
     rr=self.run(c,False,reveal);m=getattr(rr,key);vs.append({"delta":d,"basis":key,"trades":m.trades,"mean_net_return":m.mean_net_return,"profit_factor":m.profit_factor})
    except Exception as exc:vs.append({"delta":d,"error":str(exc)})
  pos=[v for v in vs if (v.get("mean_net_return") or 0)>0];return {"basis":key,"variants":vs,"positive_neighbor_fraction":len(pos)/len(vs) if vs else None}
 @staticmethod
 def _minimum_gate(r,basis):
  m=getattr(r,basis);st=r.parameter_stability.get("positive_neighbor_fraction")
  return bool(m.trades>=settings.min_oos_trades and (m.mean_net_return or 0)>0 and (m.profit_factor or 0)>1.10 and (m.max_drawdown is not None and m.max_drawdown>=-settings.max_drawdown_gate) and (st is None or st>=.5))
