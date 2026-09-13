from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException

from research_engine.cloudrun import launch_job
from research_engine.config import settings
from research_engine.db import ResearchDB
from research_engine.models import ParitySubmission, StartRunRequest
from research_engine.promotion import PromotionManager

app = FastAPI(title="BTC Autonomous Research Engine", version="0.3.0")


def authorize(x_research_secret: str | None = Header(default=None)):
    if not settings.api_secret:
        if settings.environment == "prod":
            raise HTTPException(
                status_code=503, detail="RESEARCH_API_SECRET is not configured"
            )
        return
    if x_research_secret != settings.api_secret:
        raise HTTPException(status_code=401, detail="invalid research secret")


def _timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


@app.get("/health")
async def health():
    return {"ok": True, "service": "btc-research-engine", "version": "0.3.0"}


@app.post("/runs/start", dependencies=[Depends(authorize)])
async def start_run(req: StartRunRequest):
    db = ResearchDB()
    budget = req.budget_usd or settings.run_budget_usd
    run = await db.create_run(req.mission, budget, req.notes)
    op = await launch_job(str(run["id"]))
    await db.add_event(
        str(run["id"]),
        "RUN_CREATED",
        {"budget_usd": budget, "cloud_run_operation": op},
    )
    return {"run": run, "job_operation": op, "auto_launched": op is not None}


@app.get("/runs/{run_id}", dependencies=[Depends(authorize)])
async def get_run(run_id: str):
    db = ResearchDB()
    try:
        run = await db.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        ex = await db.select(
            "btc_research_experiments",
            "experiment_id,hypothesis,status,result,rejection_reason,created_at",
            limit=20,
            order="created_at",
            descending=True,
            run_id=run_id,
        )
        pr = await db.select(
            "btc_research_promotion_packages",
            "experiment_id,signal_name,status,contract_hash,created_at",
            limit=20,
            order="created_at",
            descending=True,
            run_id=run_id,
        )
        daily = await db.daily_spend()
        return {
            "run": run,
            "daily_spend_usd": daily,
            "daily_budget_usd": settings.daily_budget_usd,
            "experiments": ex,
            "promotions": pr,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Research database temporarily unavailable; retry shortly",
        ) from exc


@app.post("/runs/{run_id}/pause", dependencies=[Depends(authorize)])
async def pause(run_id: str):
    db = ResearchDB()
    await db.update("btc_research_runs", {"status": "PAUSED"}, id=run_id)
    return {"ok": True, "status": "PAUSED"}


@app.post("/runs/{run_id}/resume", dependencies=[Depends(authorize)])
async def resume(run_id: str):
    db = ResearchDB()
    await db.update("btc_research_runs", {"status": "RUNNING"}, id=run_id)
    op = await launch_job(run_id)
    return {"ok": True, "status": "RUNNING", "job_operation": op}


@app.post("/runs/{run_id}/stop", dependencies=[Depends(authorize)])
async def stop(run_id: str):
    db = ResearchDB()
    await db.update("btc_research_runs", {"status": "STOPPED"}, id=run_id)
    return {"ok": True, "status": "STOPPED"}


@app.post("/scheduler/tick")
async def scheduler_tick():
    """Resume one controller-approved experiment without a shell command.

    This endpoint intentionally has no X-Research-Secret dependency because Cloud Run itself
    remains IAM-authenticated (--no-allow-unauthenticated). Cloud Scheduler calls it with an
    OIDC identity token. It only resumes the newest run after ChatGPT has written a *new*
    controller decision after the latest handoff, so an old directive cannot be replayed.
    """

    db = ResearchDB()
    runs = await db.select(
        "btc_research_runs",
        "id,status,phase,budget_usd,spent_usd,created_at",
        limit=1,
        order="created_at",
        descending=True,
    )
    if not runs:
        return {"ok": True, "action": "NO_RUN"}

    run = runs[0]
    run_id = str(run["id"])
    status = run.get("status")
    if status not in {"PAUSED", "BUDGET_EXHAUSTED"}:
        return {"ok": True, "action": "NOOP", "run_id": run_id, "status": status}

    remaining = await db.budget_remaining(run_id)
    if remaining <= 0.25:
        if status != "BUDGET_EXHAUSTED":
            await db.update(
                "btc_research_runs", {"status": "BUDGET_EXHAUSTED"}, id=run_id
            )
        return {
            "ok": True,
            "action": "BUDGET_EXHAUSTED",
            "run_id": run_id,
            "remaining_budget_usd": remaining,
        }

    handoffs = await db.select(
        "btc_research_events",
        "created_at,payload",
        limit=1,
        order="created_at",
        descending=True,
        run_id=run_id,
        event_type="CONTROLLER_HANDOFF_REQUIRED",
    )
    decisions = await db.select(
        "btc_research_decisions",
        "created_at,decision",
        limit=1,
        order="created_at",
        descending=True,
        run_id=run_id,
    )
    latest_decision = decisions[0] if decisions else None
    latest_handoff = handoffs[0] if handoffs else None

    if not latest_decision or not (latest_decision.get("decision") or {}).get(
        "research_directive"
    ):
        return {"ok": True, "action": "AWAITING_CONTROLLER", "run_id": run_id}

    if latest_handoff and _timestamp(latest_decision.get("created_at")) <= _timestamp(
        latest_handoff.get("created_at")
    ):
        return {
            "ok": True,
            "action": "AWAITING_FRESH_CONTROLLER_DIRECTIVE",
            "run_id": run_id,
        }

    await db.update("btc_research_runs", {"status": "RUNNING"}, id=run_id)
    await db.add_event(
        run_id,
        "SCHEDULER_AUTO_RESUME",
        {
            "controller_decision_created_at": latest_decision.get("created_at"),
            "latest_handoff_created_at": (
                latest_handoff.get("created_at") if latest_handoff else None
            ),
            "remaining_budget_usd": remaining,
        },
    )
    try:
        op = await launch_job(run_id)
    except Exception as exc:
        await db.update("btc_research_runs", {"status": "PAUSED"}, id=run_id)
        await db.add_event(
            run_id,
            "SCHEDULER_AUTO_RESUME_FAILED",
            {"error": str(exc)[:1500]},
        )
        raise HTTPException(status_code=503, detail="research job launch failed") from exc

    return {
        "ok": True,
        "action": "LAUNCHED",
        "run_id": run_id,
        "job_operation": op,
        "remaining_budget_usd": remaining,
    }


@app.get(
    "/runs/{run_id}/promotion/{experiment_id}", dependencies=[Depends(authorize)]
)
async def get_promotion(run_id: str, experiment_id: str):
    db = ResearchDB()
    rows = await db.select(
        "btc_research_promotion_packages",
        "*",
        limit=1,
        run_id=run_id,
        experiment_id=experiment_id,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="promotion package not found")
    return rows[0]


@app.post(
    "/runs/{run_id}/promotion/{experiment_id}/parity/verify",
    dependencies=[Depends(authorize)],
)
async def parity_verify(
    run_id: str, experiment_id: str, submission: ParitySubmission
):
    db = ResearchDB()
    try:
        return await PromotionManager(db).verify_and_mark(
            run_id,
            experiment_id,
            submission.vectors,
            submission.relative_tolerance,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="promotion package not found")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
