#!/usr/bin/env python3
"""Frozen stage-2 evaluator for PREPUMP_STRONG_RECLAIM_V2."""
from __future__ import annotations
import argparse,json
from pathlib import Path
import pandas as pd

RANGE_POS_MIN=0.481992337164751
MIN_YEAR_EVENTS=15
MIN_POOLED_EVENTS=40

def stats(f):
    n=len(f); ev=int(f["early_pump4"].sum()) if n else 0
    return {"count":int(n),"events":ev,"event_rate":None if not n else ev/n}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--v1-candidates",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    f=pd.read_csv(args.v1_candidates)
    f["open_time"]=pd.to_datetime(f["open_time"],utc=True)
    f["early_pump4"]=f["early_pump4"].astype(str).str.lower().map({"true":True,"false":False}).fillna(f["early_pump4"]).astype(bool)
    f["year"]=f["open_time"].dt.year
    v2=f[f["range_pos24"]>=RANGE_POS_MIN].copy()

    years={}
    year_gate={}
    for y in (2024,2025):
        p=f[f["year"]==y]; s=v2[v2["year"]==y]
        ps=stats(p); ss=stats(s)
        lift=None if not ps["event_rate"] else ss["event_rate"]/ps["event_rate"]
        years[str(y)]={"v1":ps,"v2":ss,"stage2_lift":lift}
        if ss["events"]<MIN_YEAR_EVENTS: year_gate[str(y)]="INSUFFICIENT"
        elif lift is not None and lift>=1.25: year_gate[str(y)]="PASS"
        else: year_gate[str(y)]="FAIL"

    p_all=stats(f); s_all=stats(v2)
    pooled_lift=None if not p_all["event_rate"] else s_all["event_rate"]/p_all["event_rate"]
    by_asset={}
    for sym in sorted(f["symbol"].unique()):
        ps=stats(f[f["symbol"]==sym]); ss=stats(v2[v2["symbol"]==sym])
        lift=None if not ps["event_rate"] else ss["event_rate"]/ps["event_rate"]
        by_asset[sym]={"v1":ps,"v2":ss,"stage2_lift":lift}
    shares=v2["symbol"].value_counts(normalize=True).to_dict() if len(v2) else {}
    assets_n20=[s for s,m in by_asset.items() if m["v2"]["count"]>=20]
    cross=(len(assets_n20)>=4 and max(shares.values(),default=0)<=0.50)
    pooled_ok=(s_all["events"]>=MIN_POOLED_EVENTS and s_all["event_rate"] is not None and p_all["event_rate"] is not None and s_all["event_rate"]>p_all["event_rate"])
    if all(x=="PASS" for x in year_gate.values()) and cross and pooled_ok: status="PASS"
    elif any(x=="INSUFFICIENT" for x in year_gate.values()): status="INSUFFICIENT"
    else: status="REJECT"
    out={"contract":"PREPUMP_STRONG_RECLAIM_V2","range_pos24_gte":RANGE_POS_MIN,
         "years":years,"pooled":{"v1":p_all,"v2":s_all,"stage2_lift":pooled_lift},
         "by_asset":by_asset,"candidate_shares":shares,"assets_v2_n20":assets_n20,
         "cross_asset_pass":cross,"pooled_gate":pooled_ok,"year_gate":year_gate,
         "replication_status":status}
    args.output.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(out,indent=2,sort_keys=True))
if __name__=="__main__":main()
