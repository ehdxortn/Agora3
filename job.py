from __future__ import annotations

import asyncio
import json
import os

from research_engine.orchestrator import ResearchOrchestrator


async def main() -> None:
    run_id = os.getenv("RESEARCH_RUN_ID")
    if not run_id:
        raise RuntimeError("RESEARCH_RUN_ID is required")
    orchestrator = ResearchOrchestrator()
    outputs = await orchestrator.run_until_stop(run_id)
    print(json.dumps(outputs, ensure_ascii=False, default=str))


if __name__ == "__main__":
    asyncio.run(main())
