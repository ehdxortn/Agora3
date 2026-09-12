from __future__ import annotations
import json
from pathlib import Path
from pydantic import TypeAdapter
from .config import settings
from .models import ExperimentSpec,LiteratureItem
P=Path(__file__).resolve().parent.parent/"prompts"
TOPIC_QUEUE=["BTC time-series momentum, trend persistence, and reversal evidence","BTC volatility compression, expansion, breakout, and volatility-risk evidence","BTC perpetual futures funding rate and subsequent returns","BTC open interest, deleveraging, liquidations, and forward return evidence","BTC taker flow, order-flow imbalance, long-short positioning, and microstructure","BTC on-chain activity and forward returns with publication/revision timing","BTC market regime detection and conditional strategy performance","BTC machine-learning return prediction with strict chronological OOS validation","BTC entry timing, holding-period, stop-loss, and take-profit research after costs","BTC cross-market predictors with tradable information value","negative results and replication failures in cryptocurrency trading strategies","data snooping, backtest overfitting, and leakage failures specific to crypto research"]
def prompt(n):return (P/n).read_text(encoding="utf-8")
class LiteratureResearcher:
 def __init__(self,db,openai,anthropic):self.db=db;self.openai=openai;self.anthropic=anthropic;self.adapter=TypeAdapter(list[LiteratureItem])
 async def scout_topic(self,run_id,topic):
  data,out=await self.openai.ask_json(run_id=run_id,role="literature_worker",model=settings.openai_worker_model,instructions=prompt("literature_worker.md"),prompt=f"Research topic: {topic}\nSearch current web and scholarly/indexable sources. Every URL must be grounded in the web-search results; never invent a bibliographic URL. Return balanced positive, null, contradictory and replication evidence.",effort="low",max_output_tokens=5000,web_search=True);items=self.adapter.validate_python(data)
  for item in items:
   p=item.model_dump();p.update({"run_id":run_id,"topic":topic})
   try:await self.db.insert("btc_research_literature",p)
   except Exception:pass
  await self.db.add_event(run_id,"LITERATURE_SCOUT_COMPLETE",{"topic":topic,"items":len(items),"tool_source_count":len(out.sources),"tool_sources":out.sources[:50],"model":settings.openai_worker_model,"cost_usd":out.cost_usd});return items
 async def source_count(self,run_id):return len(await self.db.select("btc_research_literature","id",limit=2000,run_id=run_id))
 async def recent_sources(self,run_id,limit=120):return await self.db.select("btc_research_literature","id,title,url,quality_tier,research_question,claim,method,dataset_period,timeframe,costs_included,leakage_risks,replication_value,tags",limit=limit,order="created_at",descending=True,run_id=run_id)
 async def synthesize_map(self,run_id):
  src=json.dumps(await self.recent_sources(run_id,160),ensure_ascii=False,default=str)[:190000];system="You are a senior BTC quantitative literature synthesizer. Compress evidence without inventing consensus. Distinguish replicated evidence, contradictory evidence, methodological weaknesses, likely dead ends, and high-value replication gaps. Return JSON only."
  data,_=await self.anthropic.ask_json(run_id=run_id,role="literature_synthesizer",model=settings.anthropic_senior_model,system=system,prompt="Build the initial research map from these records. Return {themes:[], replicated_findings:[], contradictions:[], weak_or_invalid_claims:[], high_value_replications:[], open_questions:[]}\n\n"+src,max_tokens=7000,effort="high");await self.db.add_event(run_id,"LITERATURE_MAP",data);return data
 async def propose_experiment(self,run_id,failure_memory,directive=""):
  src=json.dumps(await self.recent_sources(run_id,120),ensure_ascii=False,default=str)[:150000];fail=json.dumps(failure_memory[-50:],ensure_ascii=False,default=str)[:45000];data,_=await self.anthropic.ask_json(run_id=run_id,role="senior_researcher",model=settings.anthropic_senior_model,system=prompt("senior_researcher.md"),prompt="RESEARCH DIRECTOR DIRECTIVE:\n"+(directive or "Replicate or extend the highest-information-value prior finding.")+"\n\nPRIOR RESEARCH DATABASE:\n"+src+"\n\nFAILURE MEMORY:\n"+fail,max_tokens=5000,effort="high");return ExperimentSpec.model_validate(data)
