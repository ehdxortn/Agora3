from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .config import settings
from .db import ResearchDB
from .experiment import BTCDataLoader, ExperimentRunner
from .literature import LiteratureResearcher
from .models import ExperimentSpec
from .providers import AnthropicProvider, OpenAIProvider

P = Path(__file__).resolve().parent.parent / "prompts"


def prompt(name: str) -> str:
    return (P / name).read_text(encoding="utf-8")


class ControllerResearchCycle:
    """Run exactly one paid research experiment, then hand control back to ChatGPT.

    The chat controller owns literature curation, research-family selection, budgeting,
    interpretation, and the next directive. Paid APIs are restricted to narrow research
    roles: Sonnet designs one experiment, Terra is a one-shot failover, Python executes
    the test, and Opus is used only when the deterministic pre-holdout gate passes.
    No API research-director call and no web scouting occur in this path.
    """

    def __init__(self, db=None):
        self.db = db or ResearchDB()
        self.openai = OpenAIProvider(self.db)
        self.anthropic = AnthropicProvider(self.db)
        self.literature = LiteratureResearcher(self.db, self.openai, self.anthropic)
        self._runner = None

    async def runner(self):
        if self._runner is None:
            self._runner = ExperimentRunner(await BTCDataLoader(self.db).load())
        return self._runner

    async def latest_decision(self, run_id: str):
        rows = await self.db.select(
            "btc_research_decisions",
            "decision",
            limit=1,
            order="created_at",
            descending=True,
            run_id=run_id,
        )
        return rows[0].get("decision") if rows else None

    async def _build_spec(self, run_id: str, directive: str) -> ExperimentSpec:
        # The controller has already curated the database. Retrieve only the most relevant
        # evidence and failures; never send the whole research corpus to a paid model.
        sources = await self.literature.retrieve_sources(
            directive or "BTC causal trading edge",
            limit=min(settings.literature_retrieval_limit, 10),
        )
        if len(sources) < 4:
            fallback = await self.literature.best_sources(limit=10)
            seen = {x.get("url") for x in sources}
            sources += [x for x in fallback if x.get("url") not in seen][: 10 - len(sources)]

        source_packet = [
            {
                "id": str(x.get("id")),
                "title": x.get("title"),
                "quality_tier": x.get("quality_tier"),
                "claim": x.get("claim"),
                "method": x.get("method"),
                "timeframe": x.get("timeframe"),
                "costs_included": x.get("costs_included"),
                "leakage_risks": x.get("leakage_risks"),
                "replication_value": x.get("replication_value"),
                "tags": x.get("tags"),
            }
            for x in sources
        ]

        global_failures = await self.literature._global_failure_memory([])
        failures = self.literature.relevant_failures(global_failures, directive)[:8]
        request = (
            "EXTERNAL CHATGPT CONTROLLER DIRECTIVE:\n"
            + (directive or "Design one high-information-value causal BTC experiment.")
            + "\n\nCURATED PRIOR RESEARCH:\n"
            + json.dumps(source_packet, ensure_ascii=False, default=str)[:18000]
            + "\n\nRELEVANT FAILURE MEMORY:\n"
            + json.dumps(failures, ensure_ascii=False, default=str)[:10000]
            + "\n\nDesign exactly ONE compact falsifiable ExperimentSpec. Do not browse the web, "
              "do not request more literature, do not retune a frozen failure, and do not "
              "invent unavailable data. Keep the reasoning encoded in the structured fields concise."
        )
        await self.db.add_event(
            run_id,
            "CONTROLLER_RESEARCH_PACKET",
            {
                "source_ids": [x["id"] for x in source_packet],
                "source_count": len(source_packet),
                "failure_count": len(failures),
                "web_search_used": False,
                "controller": "CHATGPT_5_6_SOL",
            },
        )

        # One Sonnet attempt only. A deterministic billing/provider failure must not be paid
        # twice before failover. This bypasses the generic two-attempt provider helper on purpose.
        try:
            response = await self.anthropic.client.messages.parse(
                model=settings.anthropic_senior_model,
                max_tokens=2800,
                system=prompt("senior_researcher.md"),
                messages=[{"role": "user", "content": request}],
                output_config={"effort": "medium"},
                output_format=ExperimentSpec,
            )
            out = await self.anthropic._record_response(
                response,
                run_id=run_id,
                role="mechanism_researcher",
                model=settings.anthropic_senior_model,
            )
            spec = getattr(response, "parsed_output", None)
            if spec is None:
                raise RuntimeError(
                    f"Sonnet structured output missing parsed_output; stop_reason={out.stop_reason}"
                )
            return spec
        except Exception as exc:
            await self.db.add_event(
                run_id,
                "MECHANISM_RESEARCHER_FAILOVER",
                {
                    "from": "anthropic",
                    "to": "openai",
                    "error": str(exc)[:1000],
                    "retry_policy": "NO_ANTHROPIC_RETRY",
                },
            )
            spec, _ = await self.openai.ask_typed(
                output_format=ExperimentSpec,
                run_id=run_id,
                role="mechanism_researcher_failover",
                model=settings.openai_senior_model,
                instructions=prompt("senior_researcher.md"),
                prompt=request,
                effort="medium",
                max_output_tokens=3000,
                web_search=False,
            )
            return spec

    async def run_one(self, run_id: str):
        run = await self.db.get_run(run_id)
        if not run:
            raise RuntimeError(f"Unknown run_id {run_id}")
        if run.get("status") != "RUNNING":
            return {"status": run.get("status"), "message": "Run is not active"}

        remaining = await self.db.budget_remaining(run_id)
        if remaining <= 0.25:
            await self.db.update(
                "btc_research_runs", {"status": "BUDGET_EXHAUSTED"}, id=run_id
            )
            return {"status": "BUDGET_EXHAUSTED"}

        latest = await self.latest_decision(run_id)
        if not latest or not latest.get("research_directive"):
            await self.db.update(
                "btc_research_runs",
                {"status": "PAUSED", "phase": "DIRECTOR"},
                id=run_id,
            )
            await self.db.add_event(
                run_id,
                "CONTROLLER_DIRECTIVE_REQUIRED",
                {"controller": "CHATGPT_5_6_SOL"},
            )
            return {"status": "PAUSED", "reason": "CONTROLLER_DIRECTIVE_REQUIRED"}

        cycle = int(run.get("cycle_no") or 0) + 1
        await self.db.update(
            "btc_research_runs", {"cycle_no": cycle, "phase": "EXPERIMENT"}, id=run_id
        )
        directive = latest.get("research_directive", "")
        spec = await self._build_spec(run_id, directive)

        if not spec.source_research_ids:
            await self.db.update(
                "btc_research_runs", {"status": "PAUSED", "phase": "DIRECTOR"}, id=run_id
            )
            await self.db.add_event(
                run_id,
                "CONTROLLER_HANDOFF_REQUIRED",
                {"reason": "NO_PRIOR_ART_REFERENCE", "hypothesis": spec.hypothesis},
            )
            return {"status": "PAUSED", "reason": "NO_PRIOR_ART_REFERENCE"}

        spec_hash = hashlib.sha256(spec.model_dump_json().encode()).hexdigest()
        duplicate = await self.db.select(
            "btc_research_experiments",
            "id",
            limit=1,
            run_id=run_id,
            spec_hash=spec_hash,
        )
        if duplicate:
            await self.db.update(
                "btc_research_runs", {"status": "PAUSED", "phase": "DIRECTOR"}, id=run_id
            )
            await self.db.add_event(
                run_id,
                "CONTROLLER_HANDOFF_REQUIRED",
                {"reason": "DUPLICATE_SPEC", "spec_hash": spec_hash},
            )
            return {"status": "PAUSED", "reason": "DUPLICATE_SPEC"}

        runner = await self.runner()
        try:
            result = runner.run(spec, reveal_holdout=False)
        except Exception as exc:
            await self.db.insert(
                "btc_research_experiments",
                {
                    "run_id": run_id,
                    "spec_hash": spec_hash,
                    "hypothesis": spec.hypothesis,
                    "status": "FAILED",
                    "spec": spec.model_dump(mode="json"),
                    "result": {},
                    "rejection_reason": str(exc),
                },
            )
            await self.db.update(
                "btc_research_runs", {"status": "PAUSED", "phase": "DIRECTOR"}, id=run_id
            )
            await self.db.add_event(
                run_id,
                "CONTROLLER_HANDOFF_REQUIRED",
                {"reason": "EXPERIMENT_EXECUTION_FAILED", "error": str(exc)[:1200]},
            )
            return {"status": "PAUSED", "error": str(exc)}

        row = await self.db.insert(
            "btc_research_experiments",
            {
                "run_id": run_id,
                "experiment_id": result.experiment_id,
                "spec_hash": result.spec_hash,
                "hypothesis": spec.hypothesis,
                "status": "CANDIDATE_PRE_OOS" if result.passed_minimum_gate else "WEAK",
                "spec": spec.model_dump(mode="json"),
                "result": result.model_dump(mode="json"),
                "rejection_reason": None if result.passed_minimum_gate else "validation_gate_not_met",
            },
        )

        critic = None
        if result.passed_minimum_gate:
            await self.db.update("btc_research_runs", {"phase": "RED_TEAM"}, id=run_id)
            critic, _ = await self.anthropic.ask_json(
                run_id=run_id,
                role="chief_critic",
                model=settings.anthropic_critic_model,
                system=prompt("critic.md"),
                prompt=(
                    "The final holdout is SEALED. Attack this candidate using only the frozen "
                    "ExperimentSpec and pre-holdout evidence. Do not request holdout access.\nSPEC:\n"
                    + json.dumps(spec.model_dump(mode="json"), ensure_ascii=False)
                    + "\nRESULT:\n"
                    + json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
                ),
                max_tokens=3500,
                effort="high",
            )
            await self.db.update(
                "btc_research_experiments", {"critic": critic}, id=row["id"]
            )

        # Never auto-open the sealed holdout in controller mode. ChatGPT reviews the full
        # handoff packet first and explicitly decides the next action/research family.
        await self.db.update(
            "btc_research_runs", {"status": "PAUSED", "phase": "DIRECTOR"}, id=run_id
        )
        handoff = {
            "controller": "CHATGPT_5_6_SOL",
            "cycle": cycle,
            "experiment_id": result.experiment_id,
            "spec_hash": result.spec_hash,
            "passed_pre_holdout_gate": result.passed_minimum_gate,
            "holdout_revealed": False,
            "critic_verdict": (critic or {}).get("verdict") if critic else "NOT_RUN",
            "remaining_budget_usd": await self.db.budget_remaining(run_id),
            "next_step": "CHATGPT_REVIEW_AND_DIRECTIVE",
        }
        await self.db.add_event(run_id, "CONTROLLER_HANDOFF_REQUIRED", handoff)
        return {"status": "PAUSED", "phase": "DIRECTOR", **handoff}
