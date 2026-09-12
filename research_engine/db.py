from __future__ import annotations
import asyncio
from datetime import datetime,timezone
from supabase import Client,create_client
from .config import settings
class ResearchDB:
 def __init__(self):
  if not settings.supabase_url or not settings.supabase_service_role_key:raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
  self.client:Client=create_client(settings.supabase_url,settings.supabase_service_role_key)
 async def _call(self,fn,*a,**k):return await asyncio.to_thread(fn,*a,**k)
 async def insert(self,table,payload):
  def run():
   r=self.client.table(table).insert(payload).execute();return r.data[0] if r.data else payload
  return await self._call(run)
 async def update(self,table,payload,**eq):
  def run():
   q=self.client.table(table).update(payload)
   for k,v in eq.items():q=q.eq(k,v)
   return q.execute().data or []
  return await self._call(run)
 async def select(self,table,columns="*",limit=100,order=None,descending=False,**eq):
  def run():
   q=self.client.table(table).select(columns)
   for k,v in eq.items():q=q.eq(k,v)
   if order:q=q.order(order,desc=descending)
   return q.limit(limit).execute().data or []
  return await self._call(run)
 async def paged_select(self,table,columns="*",page_size=1000,order=None,**eq):
  rows=[];start=0
  while True:
   def run(start=start):
    q=self.client.table(table).select(columns)
    for k,v in eq.items():q=q.eq(k,v)
    if order:q=q.order(order)
    return q.range(start,start+page_size-1).execute().data or []
   chunk=await self._call(run);rows.extend(chunk)
   if len(chunk)<page_size:break
   start+=page_size
  return rows
 async def create_run(self,mission,budget_usd,notes=""):return await self.insert("btc_research_runs",{"mission":mission,"status":"RUNNING","phase":"LITERATURE","budget_usd":budget_usd,"spent_usd":0,"cycle_no":0,"notes":notes})
 async def get_run(self,run_id):
  rows=await self.select("btc_research_runs",limit=1,id=run_id);return rows[0] if rows else None
 async def add_event(self,run_id,event_type,payload):await self.insert("btc_research_events",{"run_id":run_id,"event_type":event_type,"payload":payload})
 async def daily_spend(self):
  start=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).isoformat()
  def run():return self.client.table("btc_research_usage").select("cost_usd").gte("created_at",start).limit(10000).execute().data or []
  rows=await self._call(run);return sum(float(x.get("cost_usd") or 0) for x in rows)
 async def record_cost(self,run_id,provider,model,role,input_tokens,output_tokens,web_searches,cost_usd,metadata=None):
  await self.insert("btc_research_usage",{"run_id":run_id,"provider":provider,"model":model,"role":role,"input_tokens":input_tokens,"output_tokens":output_tokens,"web_searches":web_searches,"cost_usd":cost_usd,"metadata":metadata or {}});run=await self.get_run(run_id)
  if run:await self.update("btc_research_runs",{"spent_usd":float(run.get("spent_usd") or 0)+float(cost_usd)},id=run_id)
 async def budget_remaining(self,run_id):
  run=await self.get_run(run_id)
  if not run:return 0.0
  run_remaining=max(0.0,float(run["budget_usd"])-float(run.get("spent_usd") or 0));daily_remaining=max(0.0,settings.daily_budget_usd-await self.daily_spend());return min(run_remaining,daily_remaining)
 async def should_continue(self,run_id):
  run=await self.get_run(run_id);return bool(run and run.get("status")=="RUNNING" and await self.budget_remaining(run_id)>0)
