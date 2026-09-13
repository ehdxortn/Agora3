from __future__ import annotations

import asyncio
import json
import os
import traceback
from datetime import datetime, timezone

from research_engine.controller_cycle import ControllerResearchCycle
from research_engine.db import ResearchDB
from research_engine.orchestrator import ResearchOrchestrator


async def _persist_fatal(run_id: str, exc: Exception) -> dict:
    payload = {
        "type": type(exc).__name__,
        "message": str(exc)[:4000],
        "traceback": traceback.format_exc(limit=20)[-12000:],
    }
    try:
        db = ResearchDB()
        await db.add_event(run_id, "JOB_FATAL", payload)
        await db.update(
            "btc_research_runs",
            {
                "status": "BLOCKED",
                "notes": "Research job stopped safely after an unhandled provider/infrastructure error. Inspect JOB_FATAL before resuming.",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            id=run_id,
        )
    except Exception as persist_error:
        payload["persistence_error"] = str(persist_error)[:2000]
        try:
            db = ResearchDB()
            await db.add_event(
                run_id,
                "JOB_FATAL_PERSISTENCE_FAILED",
                {"error": payload["persistence_error"]},
            )
        except Exception:
            pass
    return payload


def _controller_mode_enabled() -> bool:
    value = os.getenv("CHATGPT_CONTROLLER_MODE", "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


async def main() -> None:
    run_id = os.getenv("RESEARCH_RUN_ID")
    if not run_id:
        raise RuntimeError("RESEARCH_RUN_ID is required")
    try:
        if _controller_mode_enabled():
            output = await ControllerResearchCycle().run_one(run_id)
            print(json.dumps([output], ensure_ascii=False, default=str))
        else:
            orchestrator = ResearchOrchestrator()
            outputs = await orchestrator.run_until_stop(run_id)
            print(json.dumps(outputs, ensure_ascii=False, default=str))
    except Exception as exc:
        # Exit cleanly after persisting a fail-closed state. A provider or formatting
        # failure must not leave the run marked RUNNING or expose the sealed holdout.
        payload = await _persist_fatal(run_id, exc)
        print(
            json.dumps(
                {"status": "BLOCKED", "phase": "ERROR", "fatal": payload},
                ensure_ascii=False,
                default=str,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
