from __future__ import annotations
import hashlib,json
from pathlib import Path
from typing import Any
from .config import settings
from .db import ResearchDB
from .experiment import BTCDataLoader,ExperimentRunner
from .literature import LiteratureResearcher,TOPIC_QUEUE
from .models import Confidence,DirectorDecision
from .parity import build_parity_fixture
from .promotion import PromotionManager
from .providers import AnthropicProvider,OpenAIProvider
P=Path(__file__).resolve().parent.parent/"prompts"
def prompt(n):return (P/n).read_text(encoding="utf-8")
class ResearchOrchestrator:
 def __init__(self,db=None):
  self.db=db or ResearchDB();self.openai=OpenAIProvider(self.db);self.anthropic=AnthropicProvider(self.db);self.literature=LiteratureResearcher(self.db,self.openai,self.anthropic);self.promotion=PromotionManager(self.db);self._runner=None
 async def runner(self):
  if self._runner is None:self._runner=ExperimentRunner(await BTCDataLoader(self.db).load())
  return self._runner
 async def failure_memory(self,run_id,limit=60):
  rows=await self.db.select("btc_research_experiments","id,spec_hash,hypothesis,status,rejection_reason,spec,result",limit=limit,order="created_at",descending=True,run_id=run_id);return [r for r in rows if r.get("status") in {"REJECTED","FAILED","WEAK"}]
 async def run_cycle(self,run_id):
  run=await self.db.get_run(run_id)
  if not run:raise RuntimeError(f"Unknown run_id {run_id}")
  if run.get("status")!="RUNNING":return {"status":run.get("status"),"message":"Run is not active"}
  remaining=await self.db.budget_remaining(run_id)
  if remaining<=.25:await self.db.update("btc_research_runs",{"status":"BUDGET_EXHAUSTED"},id=run_id);return {"status":"BUDGET_EXHAUSTED"}
  cycle=int(run.get("cycle_no") or 0)+1;await self.db.update("btc_research_runs",{"cycle_no":cycle},id=run_id);count=await self.literature.source_count(run_id)
  if count<60:
   topic=TOPIC_QUEUE[(cycle-1)%len(TOPIC_QUEUE)];await self.db.update("btc_research_runs",{"phase":"LITERATURE"},id=run_id);items=await self.literature.scout_topic(run_id,topic);return {"status":"CONTINUE","phase":"LITERATURE","cycle":cycle,"topic":topic,"new_sources":len(items),"total_sources_approx":count+len(items)}
  await self.db.update("btc_research_runs",{"phase":"EXPERIMENT"},id=run_id);spec=await self.literature.propose_experiment(run_id,await self.failure_memory(run_id));sh=hashlib.sha256(spec.model_dump_json().encode()).hexdigest()
  if await self.db.select("btc_research_experiments","id,status",limit=3,run_id=run_id,spec_hash=sh):await self.db.add_event(run_id,"DUPLICATE_EXPERIMENT_BLOCKED",{"spec_hash":sh});return {"status":"CONTINUE","phase":"EXPERIMENT","cycle":cycle,"duplicate_blocked":True}
  runner=await self.runner()
  try:r=runner.run(spec)
  except Exception as e:
   await self.db.insert("btc_research_experiments",{"run_id":run_id,"spec_hash":sh,"hypothesis":spec.hypothesis,"status":"FAILED","spec":spec.model_dump(mode="json"),"result":{},"rejection_reason":str(e)});return {"status":"CONTINUE","phase":"EXPERIMENT","cycle":cycle,"error":str(e)}
  row=await self.db.insert("btc_research_experiments",{"run_id":run_id,"experiment_id":r.experiment_id,"spec_hash":r.spec_hash,"hypothesis":spec.hypothesis,"status":"CANDIDATE" if r.passed_minimum_gate else "WEAK","spec":spec.model_dump(mode="json"),"result":r.model_dump(mode="json"),"rejection_reason":None if r.passed_minimum_gate else "minimum_gate_not_met"})
  critic=None
  if r.passed_minimum_gate:
   await self.db.update("btc_research_runs",{"phase":"RED_TEAM"},id=run_id);critic,_=await self.anthropic.ask_json(run_id=run_id,role="chief_critic",model=settings.anthropic_critic_model,system=prompt("critic.md"),prompt="EXPERIMENT SPEC:\n"+json.dumps(spec.model_dump(mode="json"),ensure_ascii=False)+"\nRESULT:\n"+json.dumps(r.model_dump(mode="json"),ensure_ascii=False),max_tokens=4500,effort="high");await self.db.update("btc_research_experiments",{"critic":critic},id=row["id"])
  await self.db.update("btc_research_runs",{"phase":"DIRECTOR"},id=run_id);d,_=await self.openai.ask_json(run_id=run_id,role="research_director",model=settings.openai_director_model,instructions=prompt("constitution.md")+"\n\n"+prompt("director.md"),prompt="MISSION:\n"+str(run.get("mission"))+"\nSPEC:\n"+json.dumps(spec.model_dump(mode="json"),ensure_ascii=False)+"\nRESULT:\n"+json.dumps(r.model_dump(mode="json"),ensure_ascii=False)+"\nRED TEAM:\n"+json.dumps(critic or {"verdict":"NOT_RUN"},ensure_ascii=False),effort="high",max_output_tokens=4500,web_search=False);decision=DirectorDecision.model_validate(d);await self.db.insert("btc_research_decisions",{"run_id":run_id,"experiment_id":r.experiment_id,"decision":decision.model_dump(mode="json")})
  rej=decision.interpretation if decision.confidence in {Confidence.REJECTED,Confidence.WEAK} else None;await self.db.update("btc_research_experiments",{"status":decision.confidence.value,"rejection_reason":rej,"director_decision":decision.model_dump(mode="json")},id=row["id"])
  promotion=None
  if decision.next_action=="PROMOTE" and r.passed_minimum_gate and critic and critic.get("verdict")=="PASS":
   fixture=build_parity_fixture(runner,spec);pkg=await self.promotion.create_package(run_id,spec,r,"btc_"+r.spec_hash[:12],fixture);promotion=pkg.model_dump(mode="json");await self.db.update("btc_research_experiments",{"status":"PENDING_PARITY"},id=row["id"])
  if decision.research_status=="COMPLETE" or decision.next_action=="STOP":await self.db.update("btc_research_runs",{"status":"COMPLETE"},id=run_id)
  elif decision.research_status=="BLOCKED":await self.db.update("btc_research_runs",{"status":"BLOCKED"},id=run_id)
  else:await self.db.update("btc_research_runs",{"phase":"EXPERIMENT"},id=run_id)
  return {"status":decision.research_status,"phase":"DIRECTOR","cycle":cycle,"experiment_id":r.experiment_id,"minimum_gate":r.passed_minimum_gate,"critic":critic,"director":decision.model_dump(mode="json"),"promotion":promotion}
 async def run_until_stop(self,run_id,max_cycles=None):
  outs=[]
  for _ in range(max_cycles or settings.max_cycles_per_job):
   if not await self.db.should_continue(run_id):break
   x=await self.run_cycle(run_id);outs.append(x)
   if x.get("status") in {"COMPLETE","BLOCKED","BUDGET_EXHAUSTED"}:break
  if await self.db.budget_remaining(run_id)<=0:await self.db.update("btc_research_runs",{"status":"BUDGET_EXHAUSTED"},id=run_id)
  return outs
