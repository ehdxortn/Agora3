from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from pydantic import TypeAdapter
from .config import settings
from .models import ExperimentSpec,LiteratureItem
PROMPT_DIR=Path(__file__).resolve().parent.parent/"prompts"
TOPIC_QUEUE=["BTC time-series momentum, trend persistence, and reversal evidence","BTC volatility compression, expansion, breakout, and volatility-risk evidence","BTC perpetual futures funding rate and subsequent returns","BTC open interest, deleveraging, liquidations, and forward return evidence","BTC taker flow, order-flow imbalance, long-short positioning, and microstructure","BTC on-chain activity and forward returns with publication/revision timing","BTC market regime detection and conditional strategy performance","BTC machine-learning return prediction with strict chronological OOS validation","BTC entry timing, holding-period, stop-loss, and take-profit research after costs","BTC cross-market predictors with tradable information value","negative results and replication failures in cryptocurrency trading strategies","data snooping, backtest overfitting, and leakage failures specific to crypto research"]
def prompt(n):return (PROMPT_DIR/n).read_text(encoding="utf-8")
class LiteratureResearcher:
 def __init__(self,db,openai,anthropic):self.db=db;self.openai=openai;self.anthropic=anthropic;self.adapter=TypeAdapter(list[LiteratureItem])
 async def scout_topic(self,run_id,topic):
  data,out=await self.openai.ask_json(run_id=run_id,role="literature_worker",model=settings.openai_worker_model,instructions=prompt("literature_worker.md"),prompt=f"Research topic: {topic}\nSearch current web and scholarly/indexable sources. Return balanced positive, null, and contradictory evidence.",effort="low",max_output_tokens=5000,web_search=True)
  items=self.adapter.validate_python(data)
  for item in items:
   p=item.model_dump();p.update({"run_id":run_id,"topic":topic})
   try:await self.db.insert("btc_research_literature",p)
   except Exception:pass
  await self.db.add_event(run_id,"LITERATURE_SCOUT_COMPLETE",{"topic":topic,"items":len(items),"model":settings.openai_worker_model,"cost_usd":out.cost_usd});return items
 async def source_count(self,run_id):return len(await self.db.select("btc_research_literature","id",limit=1000,run_id=run_id))
 async def recent_sources(self,run_id,limit=80):return await self.db.select("btc_research_literature","id,title,url,quality_tier,research_question,claim,method,dataset_period,timeframe,costs_included,leakage_risks,replication_value,tags",limit=limit,order="created_at",descending=True,run_id=run_id)
 async def propose_experiment(self,run_id,failure_memory):
  src=json.dumps(await self.recent_sources(run_id,70),ensure_ascii=False,default=str)[:100000]; fail=json.dumps(failure_memory[-40:],ensure_ascii=False,default=str)[:35000]
  data,_=await self.anthropic.ask_json(run_id=run_id,role="senior_researcher",model=settings.anthropic_senior_model,system=prompt("senior_researcher.md"),prompt="PRIOR RESEARCH DATABASE:\n"+src+"\n\nFAILURE MEMORY:\n"+fail+"\n\nPropose the single highest expected-information-value replication or extension.",max_tokens=5000,effort="high")
  return ExperimentSpec.model_validate(data)
