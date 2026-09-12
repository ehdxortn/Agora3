from __future__ import annotations

import os
from fastapi import Depends, FastAPI, Header, HTTPException

from research_engine.cloudrun import launch_job
from research_engine.config import settings
from research_engine.db import ResearchDB
from research_engine.models import StartRunRequest

app = FastAPI(title="BTC Autonomous Research Engine", version="0.1.0")


def authorize(x_research_secret: str | None = Header(default=None)) -> None:
    if settings.api_secret and x_research_secret != settings.api_secret:
        raise HTTPException(status_code=401, detail="invalid research secret")


@app.get("/health")
async def health():
    return {"ok": True, "service": "btc-research-engine", "version": "0.1.0"}


@app.post("/runs/start", dependencies=[Depends(authorize)])
async def start_run(req: StartRunRequest):
    db = ResearchDB()
    budget = req.budget_usd or settings.run_budget_usd
    run = await db.create_run(req.mission, budget, req.notes)
    operation = await launch_job(str(run["id"]))
    await db.add_event(str(run["id"]), "RUN_CREATED", {"budget_usd": budget, "cloud_run_operation": operation})
    return {"run": run, "job_operation": operation, "auto_launched": operation is not None}


@app.get("/runs/{run_id}", dependencies=[Depends(authorize)])
async def get_run(run_id: str):
    db = ResearchDB()
    run = await db.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    experiments = await db.select("btc_research_experiments","experiment_id,hypothesis,status,result,rejection_reason,created_at",limit=20,order="created_at",descending=True,run_id=run_id)
    promotions = await db.select("btc_research_promotion_packages","experiment_id,signal_name,status,contract_hash,created_at",limit=20,order="created_at",descending=True,run_id=run_id)
    return {"run": run, "experiments": experiments, "promotions": promotions}


@app.post("/runs/{run_id}/pause", dependencies=[Depends(authorize)])
async def pause_run(run_id: str):
    db = ResearchDB(); await db.update("btc_research_runs", {"status": "PAUSED"}, id=run_id)
    return {"ok": True, "status": "PAUSED"}


@app.post("/runs/{run_id}/resume", dependencies=[Depends(authorize)])
async def resume_run(run_id: str):
    db = ResearchDB(); await db.update("btc_research_runs", {"status": "RUNNING"}, id=run_id)
    operation = await launch_job(run_id)
    return {"ok": True, "status": "RUNNING", "job_operation": operation}


@app.post("/runs/{run_id}/stop", dependencies=[Depends(authorize)])
async def stop_run(run_id: str):
    db = ResearchDB(); await db.update("btc_research_runs", {"status": "STOPPED"}, id=run_id)
    return {"ok": True, "status": "STOPPED"}


@app.get("/runs/{run_id}/promotion/{experiment_id}", dependencies=[Depends(authorize)])
async def promotion_package(run_id: str, experiment_id: str):
    db = ResearchDB()
    rows = await db.select("btc_research_promotion_packages", "*", limit=1, run_id=run_id, experiment_id=experiment_id)
    if not rows:
        raise HTTPException(status_code=404, detail="promotion package not found")
    return rows[0]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
