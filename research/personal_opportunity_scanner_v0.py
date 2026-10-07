#!/usr/bin/env python3
"""Shadow-only market snapshot for the private trading-copilot research track."""
from __future__ import annotations
import argparse, json, time, urllib.parse, urllib.request
from pathlib import Path
import pandas as pd

UPBIT="https://api.upbit.com"
BINANCE="https://data-api.binance.vision"
DIST=-0.05356

def get(url):
    req=urllib.request.Request(url,headers={"Accept":"application/json","User-Agent":"Agora3-ShadowScanner/0.1"})
    with urllib.request.urlopen(req,timeout=30) as r:
        return json.loads(r.read().decode())

def upbit_markets():
    m=get(UPBIT+"/v1/market/all?is_details=false")
    out={x["market"].split("-",1)[1]:x for x in m if x["market"].startswith("KRW-")}
    syms=list(out)
    for i in range(0,len(syms),80):
        names=[f"KRW-{s}" for s in syms[i:i+80]]
        q=urllib.parse.urlencode({"markets":",".join(names)})
        for x in get(UPBIT+"/v1/ticker?"+q):
            out[x["market"].split("-",1)[1]]["ticker"]=x
        time.sleep(.12)
    return out

def binance_markets():
    info=get(BINANCE+"/api/v3/exchangeInfo")
    active={x["baseAsset"] for x in info["symbols"] if x.get("quoteAsset")=="USDT" and x.get("status")=="TRADING" and x.get("isSpotTradingAllowed",True)}
    tick={}
    for x in get(BINANCE+"/api/v3/ticker/24hr"):
        s=x.get("symbol","")
        if s.endswith("USDT") and s[:-4] in active:
            tick[s[:-4]]=x
    return active,tick

def upbit_candles(symbol,minutes,count):
    q=urllib.parse.urlencode({"market":f"KRW-{symbol}","count":count})
    a=get(f"{UPBIT}/v1/candles/minutes/{minutes}?{q}")
    rows=[{"t":pd.Timestamp(x["candle_date_time_utc"],tz="UTC"),"h":float(x["high_price"]),"l":float(x["low_price"]),"c":float(x["trade_price"]),"qv":float(x.get("candle_acc_trade_price") or 0)} for x in a]
    f=pd.DataFrame(rows).sort_values("t")
    now=pd.Timestamp.now(tz="UTC")
    return f[f["t"]+pd.Timedelta(minutes=minutes)<=now].reset_index(drop=True)

def binance_1h(symbol,count=40):
    q=urllib.parse.urlencode({"symbol":symbol+"USDT","interval":"1h","limit":count})
    a=get(BINANCE+"/api/v3/klines?"+q)
    rows=[{"t":pd.to_datetime(int(x[0]),unit="ms",utc=True),"ct":pd.to_datetime(int(x[6]),unit="ms",utc=True),"c":float(x[4])} for x in a]
    f=pd.DataFrame(rows).sort_values("t")
    return f[f["ct"]<=pd.Timestamp.now(tz="UTC")].reset_index(drop=True)

def inspect(symbol,meta,bt):
    h=upbit_candles(symbol,60,40); m=upbit_candles(symbol,15,50); b=binance_1h(symbol)
    if len(h)<30 or len(m)<34 or len(b)<3:return None
    c=float(h.iloc[-1].c); r1=c/float(h.iloc[-2].c)-1; r4=c/float(h.iloc[-5].c)-1
    p=h.iloc[-25:-1]; hi=float(p.h.max()); lo=float(p.l.min())
    d=c/hi-1; pos=(c-lo)/(hi-lo) if hi>lo else None
    r15=float(m.iloc[-1].c/float(m.iloc[-2].c)-1)
    a15=float(m.iloc[-1].qv)/(float(m.iloc[-33:-1].qv.median()) or 1)
    a1=float(h.iloc[-1].qv)/(float(h.iloc[-25:-1].qv.mean()) or 1)
    br1=float(b.iloc[-1].c/float(b.iloc[-2].c)-1)
    flag=(r4<.03 and d<=DIST and r1>0 and pos is not None and pos>=.25)
    state="DRAWDOWN_RECLAIM_V1" if flag else ("LATE_ALREADY_MOVED" if r4>=.03 else "OBSERVE")
    t=meta.get("ticker",{})
    return {"symbol":symbol,"state":state,"price_krw":c,"ret15":r15,"ret1":r1,"ret4":r4,"dist_prior24_high":d,"range_pos24":pos,"upbit_15m_activity":a15,"upbit_1h_activity":a1,"binance_ret1":br1,"binance_minus_upbit_ret1":br1-r1,"upbit_24h_value_krw":float(t.get("acc_trade_price_24h") or 0),"binance_24h_quote_usdt":float(bt.get("quoteVolume") or 0),"validated_signal":False}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--out-dir",type=Path,required=True); ap.add_argument("--top-n",type=int,default=20)
    a=ap.parse_args(); a.out_dir.mkdir(parents=True,exist_ok=True)
    u=upbit_markets(); active,bt=binance_markets()
    dual=[s for s in u if s in active and s in bt]
    dual.sort(key=lambda s:float(u[s].get("ticker",{}).get("acc_trade_price_24h") or 0),reverse=True)
    rows=[]; errors=[]
    for s in dual[:a.top_n]:
        try:
            x=inspect(s,u[s],bt[s])
            if x: rows.append(x)
        except Exception as e: errors.append({"symbol":s,"error":type(e).__name__})
        time.sleep(.12)
    order={"DRAWDOWN_RECLAIM_V1":0,"OBSERVE":1,"LATE_ALREADY_MOVED":2}
    rows.sort(key=lambda x:(order.get(x["state"],9),-x["upbit_24h_value_krw"]))
    out={"scanner":"PERSONAL_OPPORTUNITY_SCANNER_V0","mode":"SHADOW_ONLY","generated_at":pd.Timestamp.now(tz="UTC").isoformat(),"dual_listed_count":len(dual),"inspected":len(rows),"results":rows,"errors":errors,"warning":"Research snapshot only; V1 flag is not validated as a standalone trading signal."}
    (a.out_dir/"scanner_v0.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    pd.DataFrame(rows).to_csv(a.out_dir/"scanner_v0.csv",index=False)
    print(json.dumps({"dual":len(dual),"inspected":len(rows),"v1_candidates":[x for x in rows if x["state"]=="DRAWDOWN_RECLAIM_V1"],"late":sum(x["state"]=="LATE_ALREADY_MOVED" for x in rows),"errors":errors},ensure_ascii=False))

if __name__=="__main__": main()
