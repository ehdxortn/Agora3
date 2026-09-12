from __future__ import annotations
import os
from fastapi import Depends,FastAPI,Header,HTTPException
from research_engine.cloudrun import launch_job
from research_engine.config import settings
from research_engine.db import ResearchDB
from research_engine.models import ParitySubmission,StartRunRequest
from research_engine.promotion import PromotionManager
app=FastAPI(title="BTC Autonomous Research Engine",version="0.2.0")
def authorize(x_research_secret:str|None=Header(default=None)):
 if not settings.api_secret:
  if settings.environment=="prod":raise HTTPException(status_code=503,detail="RESEARCH_API_SECRET is not configured")
  return
 if x_research_secret!=settings.api_secret:raise HTTPException(status_code=401,detail="invalid research secret")
@app.get("/health")
async def health():return {"ok":True,"service":"btc-research-engine","version":"0.2.0"}
@app.post("/runs/start",dependencies=[Depends(authorize)])
async def start_run(req:StartRunRequest):
 db=ResearchDB();budget=req.budget_usd or settings.run_budget_usd;run=await db.create_run(req.mission,budget,req.notes);op=await launch_job(str(run["id"]));await db.add_event(str(run["id"]),"RUN_CREATED",{"budget_usd":budget,"cloud_run_operation":op});return {"run":run,"job_operation":op,"auto_launched":op is not None}
@app.get("/runs/{run_id}",dependencies=[Depends(authorize)])
async def get_run(run_id:str):
 db=ResearchDB();run=await db.get_run(run_id)
 if not run:raise HTTPException(status_code=404,detail="run not found")
 ex=await db.select("btc_research_experiments","experiment_id,hypothesis,status,result,rejection_reason,created_at",limit=20,order="created_at",descending=True,run_id=run_id);pr=await db.select("btc_research_promotion_packages","experiment_id,signal_name,status,contract_hash,created_at",limit=20,order="created_at",descending=True,run_id=run_id);return {"run":run,"daily_spend_usd":await db.daily_spend(),"daily_budget_usd":settings.daily_budget_usd,"experiments":ex,"promotions":pr}
@app.post("/runs/{run_id}/pause",dependencies=[Depends(authorize)])
async def pause(run_id:str):db=ResearchDB();await db.update("btc_research_runs",{"status":"PAUSED"},id=run_id);return {"ok":True,"status":"PAUSED"}
@app.post("/runs/{run_id}/resume",dependencies=[Depends(authorize)])
async def resume(run_id:str):db=ResearchDB();await db.update("btc_research_runs",{"status":"RUNNING"},id=run_id);op=await launch_job(run_id);return {"ok":True,"status":"RUNNING","job_operation":op}
@app.post("/runs/{run_id}/stop",dependencies=[Depends(authorize)])
async def stop(run_id:str):db=ResearchDB();await db.update("btc_research_runs",{"status":"STOPPED"},id=run_id);return {"ok":True,"status":"STOPPED"}
@app.get("/runs/{run_id}/promotion/{experiment_id}",dependencies=[Depends(authorize)])
async def get_promotion(run_id:str,experiment_id:str):
 db=ResearchDB();rows=await db.select("btc_research_promotion_packages","*",limit=1,run_id=run_id,experiment_id=experiment_id)
 if not rows:raise HTTPException(status_code=404,detail="promotion package not found")
 return rows[0]
@app.post("/runs/{run_id}/promotion/{experiment_id}/parity/verify",dependencies=[Depends(authorize)])
async def parity_verify(run_id:str,experiment_id:str,submission:ParitySubmission):
 db=ResearchDB()
 try:return await PromotionManager(db).verify_and_mark(run_id,experiment_id,submission.vectors,submission.relative_tolerance)
 except LookupError:raise HTTPException(status_code=404,detail="promotion package not found")
if __name__=="__main__":
 import uvicorn;uvicorn.run(app,host="0.0.0.0",port=int(os.getenv("PORT","8080")))
