from __future__ import annotations
import hashlib,json,math
import pandas as pd

def dataset_fingerprint(raw):
 cols=sorted([c for c in raw.columns if c not in {"symbol"}]);x=raw[cols].copy()
 for c in x.columns:
  if pd.api.types.is_datetime64_any_dtype(x[c]):x[c]=pd.to_datetime(x[c],utc=True).dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
 canonical=x.to_json(orient="split",date_format="iso",date_unit="us",double_precision=15);return {"rows":len(x),"first_open_time":pd.Timestamp(raw.open_time.iloc[0]).isoformat() if len(raw) else None,"last_open_time":pd.Timestamp(raw.open_time.iloc[-1]).isoformat() if len(raw) else None,"sha256":hashlib.sha256(canonical.encode()).hexdigest(),"columns":cols}

def build_parity_fixture(runner,spec,rows=80):
 df=runner.feature_engine.apply(runner.raw.copy(),spec.features);names=[f.name for f in spec.features];u=df.dropna(subset=names+["open","close"]).reset_index(drop=True);train=u.iloc[:int(len(u)*spec.train_fraction)];th=runner._resolve_thresholds(train,spec.conditions);sig=runner._build_signal(u,spec.conditions,th);tail=u.tail(min(rows,max(10,len(u)//4)));vec=[]
 for idx,row in tail.iterrows():vec.append({"open_time":pd.Timestamp(row.open_time).isoformat(),"decision_time":pd.Timestamp(row.decision_time).isoformat(),"close":round(float(row.close),10),"features":{n:round(float(row[n]),12) for n in names},"signal":bool(sig.loc[idx])})
 raw=json.dumps(vec,sort_keys=True,separators=(",",":"));return {"resolved_thresholds":{str(k):float(v) for k,v in th.items()},"vectors":vec,"fixture_sha256":hashlib.sha256(raw.encode()).hexdigest(),"dataset_fingerprint":dataset_fingerprint(runner.raw),"required_match":"identical timestamps/signals and feature/close values within configured relative tolerance"}

def verify_parity(expected,observed,tolerance=1e-10):
 ev=expected.get("vectors",[]);em={x.get("open_time"):x for x in ev};om={x.get("open_time"):x for x in observed};m=[]
 if set(em)!=set(om):m.append({"type":"TIMESTAMP_SET_MISMATCH","missing":sorted(set(em)-set(om))[:20],"extra":sorted(set(om)-set(em))[:20]})
 for ts,e in em.items():
  o=om.get(ts)
  if not o:continue
  if bool(e.get("signal"))!=bool(o.get("signal")):m.append({"type":"SIGNAL_MISMATCH","open_time":ts,"expected":e.get("signal"),"observed":o.get("signal")})
  for key,a in e.get("features",{}).items():
   if key not in o.get("features",{}):m.append({"type":"FEATURE_MISSING","open_time":ts,"feature":key});continue
   b=float(o["features"][key]);a=float(a)
   if not math.isfinite(b) or abs(a-b)>tolerance*max(1.0,abs(a)):m.append({"type":"FEATURE_MISMATCH","open_time":ts,"feature":key,"expected":a,"observed":b})
  if "close" in o:
   a=float(e.get("close"));b=float(o.get("close"))
   if not math.isfinite(b) or abs(a-b)>tolerance*max(1.0,abs(a)):m.append({"type":"CLOSE_MISMATCH","open_time":ts,"expected":a,"observed":b})
  if len(m)>=100:break
 return {"passed":len(m)==0,"expected_vectors":len(ev),"observed_vectors":len(observed),"mismatch_count":len(m),"mismatches":m[:100],"relative_tolerance":tolerance}
