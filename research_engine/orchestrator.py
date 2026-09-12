from __future__ import annotations
import hashlib,json
from pathlib import Path
from .config import settings
from .db import ResearchDB
from .experiment import BTCDataLoader,ExperimentRunner
from .literature import LiteratureResearcher,TOPIC_QUEUE
from .models import Confidence,DirectorDecision,ExperimentSpec
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
  rows=await self.db.select("btc_research_experiments","id,spec_hash,hypothesis,status,rejection_reason,spec,result",limit=limit,order="created_at",descending=True,run_id=run_id);return [r for r in rows if r.get("status") in {"REJECTED","FAILED","WEAK","OOS_REJECTED"}]
 async def latest_decision(self,run_id):
  rows=await self.db.select("btc_research_decisions","decision",limit=1,order="created_at",descending=True,run_id=run_id);return rows[0].get("decision") if rows else None
 async def holdout_count(self):return len(await self.db.select("btc_research_events","id",limit=settings.max_holdout_evaluations+1,event_type="HOLDOUT_EXPOSED"))
 async def initial_director_plan(self,run_id,run):
  research_map=await self.literature.synthesize_map(run_id);d,_=await self.openai.ask_json(run_id=run_id,role="research_director",model=settings.openai_director_model,instructions=prompt("constitution.md")+"\n\n"+prompt("director.md"),prompt="No experiment has been run yet and the final holdout is sealed. Here is the lower-tier literature synthesis. Command the first replication/research direction. Do not claim a validated edge.\nMISSION:\n"+str(run.get("mission"))+"\nLITERATURE MAP:\n"+json.dumps(research_map,ensure_ascii=False),effort="high",max_output_tokens=5000,web_search=False);decision=DirectorDecision.model_validate(d)
  if decision.confidence in {Confidence.ROBUST_CANDIDATE,Confidence.PRODUCTION_CANDIDATE}:decision.confidence=Confidence.WEAK
  await self.db.insert("btc_research_decisions",{"run_id":run_id,"experiment_id":None,"decision":decision.model_dump(mode="json")});await self.db.add_event(run_id,"INITIAL_DIRECTOR_PLAN",decision.model_dump(mode="json"))
  if decision.next_action=="LITERATURE" and decision.research_directive:await self.literature.scout_topic(run_id,"Director-requested prior art: "+decision.research_directive[:600])
  return decision
 async def _choose_spec(self,run_id,directive,latest):
  failures=await self.failure_memory(run_id);spec=None
  if latest and latest.get("next_experiment"):
   try:spec=ExperimentSpec.model_validate(latest["next_experiment"])
   except Exception:spec=None
  if spec is None:spec=await self.literature.propose_experiment(run_id,failures,directive)
  if not spec.source_research_ids:
   await self.literature.scout_topic(run_id,"Prior-art check before experiment: "+spec.hypothesis[:500]);spec=await self.literature.propose_experiment(run_id,failures,(directive+" Cite at least one newly checked prior-research id.").strip())
  return spec
 async def run_cycle(self,run_id):
  run=await self.db.get_run(run_id)
  if not run:raise RuntimeError(f"Unknown run_id {run_id}")
  if run.get("status")!="RUNNING":return {"status":run.get("status"),"message":"Run is not active"}
  remaining=await self.db.budget_remaining(run_id)
  if remaining<=.25:await self.db.update("btc_research_runs",{"status":"BUDGET_EXHAUSTED"},id=run_id);return {"status":"BUDGET_EXHAUSTED"}
  cycle=int(run.get("cycle_no") or 0)+1;await self.db.update("btc_research_runs",{"cycle_no":cycle},id=run_id);count=await self.literature.source_count(run_id)
  if count<settings.literature_min_sources or cycle<=len(TOPIC_QUEUE):
   topic=TOPIC_QUEUE[(cycle-1)%len(TOPIC_QUEUE)];await self.db.update("btc_research_runs",{"phase":"LITERATURE"},id=run_id);items=await self.literature.scout_topic(run_id,topic);return {"status":"CONTINUE","phase":"LITERATURE","cycle":cycle,"topic":topic,"new_sources":len(items),"total_sources_approx":count+len(items)}
  latest=await self.latest_decision(run_id)
  if latest is None:
   await self.db.update("btc_research_runs",{"phase":"DIRECTOR"},id=run_id);plan=await self.initial_director_plan(run_id,run);return {"status":"CONTINUE","phase":"DIRECTOR","cycle":cycle,"initial_plan":plan.model_dump(mode="json")}
  directive=latest.get("research_directive","");await self.db.update("btc_research_runs",{"phase":"EXPERIMENT"},id=run_id);spec=await self._choose_spec(run_id,directive,latest)
  if not spec.source_research_ids:
   await self.db.add_event(run_id,"EXPERIMENT_BLOCKED_NO_PRIOR_ART",{"hypothesis":spec.hypothesis});return {"status":"CONTINUE","phase":"EXPERIMENT","cycle":cycle,"blocked":"NO_PRIOR_ART_REFERENCE"}
  sh=hashlib.sha256(spec.model_dump_json().encode()).hexdigest()
  if await self.db.select("btc_research_experiments","id",limit=1,run_id=run_id,spec_hash=sh):
   spec=await self.literature.propose_experiment(run_id,await self.failure_memory(run_id),(directive+" The exact prior ExperimentSpec already exists; design a materially different falsifiable test.").strip());sh=hashlib.sha256(spec.model_dump_json().encode()).hexdigest()
   if await self.db.select("btc_research_experiments","id",limit=1,run_id=run_id,spec_hash=sh):await self.db.add_event(run_id,"DUPLICATE_EXPERIMENT_BLOCKED",{"spec_hash":sh});return {"status":"CONTINUE","phase":"EXPERIMENT","cycle":cycle,"duplicate_blocked":True}
  runner=await self.runner()
  try:result=runner.run(spec,reveal_holdout=False)
  except Exception as exc:
   await self.db.insert("btc_research_experiments",{"run_id":run_id,"spec_hash":sh,"hypothesis":spec.hypothesis,"status":"FAILED","spec":spec.model_dump(mode="json"),"result":{},"rejection_reason":str(exc)});return {"status":"CONTINUE","phase":"EXPERIMENT","cycle":cycle,"error":str(exc)}
  row=await self.db.insert("btc_research_experiments",{"run_id":run_id,"experiment_id":result.experiment_id,"spec_hash":result.spec_hash,"hypothesis":spec.hypothesis,"status":"CANDIDATE_PRE_OOS" if result.passed_minimum_gate else "WEAK","spec":spec.model_dump(mode="json"),"result":result.model_dump(mode="json"),"rejection_reason":None if result.passed_minimum_gate else "validation_gate_not_met"})
  critic=None;final_result=None
  if result.passed_minimum_gate:
   await self.db.update("btc_research_runs",{"phase":"RED_TEAM"},id=run_id);critic,_=await self.anthropic.ask_json(run_id=run_id,role="chief_critic",model=settings.anthropic_critic_model,system=prompt("critic.md"),prompt="The final holdout is SEALED. Attack this candidate using only frozen ExperimentSpec and train/validation evidence.\nSPEC:\n"+json.dumps(spec.model_dump(mode="json"),ensure_ascii=False)+"\nRESULT:\n"+json.dumps(result.model_dump(mode="json"),ensure_ascii=False),max_tokens=4500,effort="high");await self.db.update("btc_research_experiments",{"critic":critic},id=row["id"])
   if critic.get("verdict")=="PASS":
    used=await self.holdout_count()
    if used>=settings.max_holdout_evaluations:
     await self.db.add_event(run_id,"HOLDOUT_BUDGET_EXHAUSTED",{"used":used,"limit":settings.max_holdout_evaluations});await self.db.update("btc_research_runs",{"status":"BLOCKED"},id=run_id);return {"status":"BLOCKED","reason":"GLOBAL_FINAL_HOLDOUT_EVALUATION_LIMIT_REACHED"}
    await self.db.add_event(run_id,"HOLDOUT_EXPOSED",{"experiment_id":result.experiment_id,"ordinal":used+1,"limit":settings.max_holdout_evaluations});final_result=runner.run(spec,stability=False,reveal_holdout=True,experiment_id=result.experiment_id);final_result.parameter_stability=result.parameter_stability;st=result.parameter_stability.get("positive_neighbor_fraction");final_result.passed_minimum_gate=bool(final_result.passed_minimum_gate and (st is None or st>=.5));await self.db.update("btc_research_experiments",{"result":final_result.model_dump(mode="json"),"status":"CANDIDATE_OOS" if final_result.passed_minimum_gate else "OOS_REJECTED","rejection_reason":None if final_result.passed_minimum_gate else "sealed_holdout_gate_not_met"},id=row["id"])
  judged=final_result or result;await self.db.update("btc_research_runs",{"phase":"DIRECTOR"},id=run_id);holdouts=await self.holdout_count()
  d,_=await self.openai.ask_json(run_id=run_id,role="research_director",model=settings.openai_director_model,instructions=prompt("constitution.md")+"\n\n"+prompt("director.md"),prompt="MISSION:\n"+str(run.get("mission"))+"\nSPEC:\n"+json.dumps(spec.model_dump(mode="json"),ensure_ascii=False)+"\nRESULT:\n"+json.dumps(judged.model_dump(mode="json"),ensure_ascii=False)+"\nRED TEAM:\n"+json.dumps(critic or {"verdict":"NOT_RUN"},ensure_ascii=False)+f"\nHOLDOUT REVEALED: {judged.holdout_revealed}\nGLOBAL HOLDOUT USES: {holdouts}/{settings.max_holdout_evaluations}",effort="high",max_output_tokens=4500,web_search=False);decision=DirectorDecision.model_validate(d)
  if not judged.holdout_revealed and decision.confidence in {Confidence.ROBUST_CANDIDATE,Confidence.PRODUCTION_CANDIDATE}:decision.confidence=Confidence.CANDIDATE;decision.interpretation="Confidence capped because the final holdout remains sealed. "+decision.interpretation;await self.db.add_event(run_id,"DIRECTOR_CONFIDENCE_CAPPED",{"experiment_id":judged.experiment_id})
  await self.db.insert("btc_research_decisions",{"run_id":run_id,"experiment_id":judged.experiment_id,"decision":decision.model_dump(mode="json")});rej=decision.interpretation if decision.confidence in {Confidence.REJECTED,Confidence.WEAK} else None;await self.db.update("btc_research_experiments",{"status":decision.confidence.value if not (final_result and not final_result.passed_minimum_gate) else "OOS_REJECTED","rejection_reason":rej or ("sealed_holdout_gate_not_met" if final_result and not final_result.passed_minimum_gate else None),"director_decision":decision.model_dump(mode="json")},id=row["id"])
  promotion=None
  if decision.next_action=="PROMOTE" and final_result and final_result.passed_minimum_gate and critic and critic.get("verdict")=="PASS":
   fixture=build_parity_fixture(runner,spec);pkg=await self.promotion.create_package(run_id,spec,final_result,"btc_"+final_result.spec_hash[:12],fixture);promotion=pkg.model_dump(mode="json");await self.db.update("btc_research_experiments",{"status":"PENDING_PARITY"},id=row["id"])
  if decision.next_action=="LITERATURE" and decision.research_directive:await self.literature.scout_topic(run_id,"Director-requested prior art: "+decision.research_directive[:600])
  if decision.research_status=="COMPLETE" or decision.next_action=="STOP":await self.db.update("btc_research_runs",{"status":"COMPLETE"},id=run_id)
  elif decision.research_status=="BLOCKED":await self.db.update("btc_research_runs",{"status":"BLOCKED"},id=run_id)
  else:await self.db.update("btc_research_runs",{"phase":"EXPERIMENT"},id=run_id)
  return {"status":decision.research_status,"phase":"DIRECTOR","cycle":cycle,"experiment_id":judged.experiment_id,"holdout_revealed":judged.holdout_revealed,"gate":judged.passed_minimum_gate,"critic":critic,"director":decision.model_dump(mode="json"),"promotion":promotion}
 async def run_until_stop(self,run_id,max_cycles=None):
  out=[]
  for _ in range(max_cycles or settings.max_cycles_per_job):
   if not await self.db.should_continue(run_id):break
   x=await self.run_cycle(run_id);out.append(x)
   if x.get("status") in {"COMPLETE","BLOCKED","BUDGET_EXHAUSTED"}:break
  if await self.db.budget_remaining(run_id)<=0:await self.db.update("btc_research_runs",{"status":"BUDGET_EXHAUSTED"},id=run_id)
  return out
