from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

from .config import settings
from .models import ExperimentSpec, LiteratureBatch, LiteratureItem, LiteratureMap

P = Path(__file__).resolve().parent.parent / "prompts"
TOPIC_QUEUE = [
    "BTC time-series momentum, trend persistence, and reversal evidence",
    "BTC volatility compression, expansion, breakout, and volatility-risk evidence",
    "BTC perpetual futures funding rate and subsequent returns",
    "BTC open interest, deleveraging, liquidations, and forward return evidence",
    "BTC taker flow, order-flow imbalance, long-short positioning, and microstructure",
    "BTC on-chain activity and forward returns with publication/revision timing",
    "BTC market regime detection and conditional strategy performance",
    "BTC machine-learning return prediction with strict chronological OOS validation",
    "BTC entry timing, holding-period, stop-loss, and take-profit research after costs",
    "BTC cross-market predictors with tradable information value",
    "negative results and replication failures in cryptocurrency trading strategies",
    "data snooping, backtest overfitting, and leakage failures specific to crypto research",
]


def prompt(name):
    return (P / name).read_text(encoding="utf-8")


def _hostname(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


class LiteratureResearcher:
    def __init__(self, db, openai, anthropic):
        self.db = db
        self.openai = openai
        self.anthropic = anthropic

    async def _event(self, run_id, event_type, payload):
        try:
            await self.db.add_event(run_id, event_type, payload)
        except Exception:
            pass

    async def scout_topic(self, run_id, topic):
        worker_prompt = (
            f"Research topic: {topic}\n"
            "Search current web and scholarly/indexable sources. Every URL must be grounded "
            "in the web-search results; never invent a bibliographic URL. Return balanced "
            "positive, null, contradictory and replication evidence."
        )
        parse_mode = "OPENAI_STRUCTURED"
        try:
            batch, out = await self.openai.ask_typed(
                output_format=LiteratureBatch,
                run_id=run_id,
                role="literature_worker",
                model=settings.openai_worker_model,
                instructions=prompt("literature_worker.md"),
                prompt=worker_prompt,
                effort="low",
                max_output_tokens=5000,
                web_search=True,
            )
            items = batch.items
            invalid = []
        except Exception as structured_error:
            parse_mode = "OPENAI_JSON_FALLBACK"
            await self._event(
                run_id,
                "LITERATURE_STRUCTURED_FALLBACK",
                {"topic": topic, "error": str(structured_error)[:1000]},
            )
            data, out = await self.openai.ask_json(
                run_id=run_id,
                role="literature_worker_fallback",
                model=settings.openai_worker_model,
                instructions=prompt("literature_worker.md"),
                prompt=(
                    worker_prompt
                    + "\n\nIf structured output is unavailable, return one JSON object with "
                    'exactly one key "items" containing the source array.'
                ),
                effort="low",
                max_output_tokens=6500,
                web_search=True,
            )
            raw_items = data.get("items", []) if isinstance(data, dict) else data
            if not isinstance(raw_items, list):
                raw_items = [raw_items]
            items = []
            invalid = []
            for index, raw in enumerate(raw_items):
                try:
                    items.append(LiteratureItem.model_validate(raw))
                except Exception as exc:
                    invalid.append({"index": index, "error": str(exc)[:1200]})

        source_hosts = {_hostname(url) for url in out.sources if _hostname(url)}
        grounded = []
        questionable = []
        for item in items:
            item_host = _hostname(item.url)
            if source_hosts and item_host and item_host not in source_hosts:
                questionable.append({"title": item.title[:180], "url": item.url})
            grounded.append(item)

        inserted = 0
        for item in grounded:
            payload = item.model_dump()
            payload.update({"run_id": run_id, "topic": topic})
            try:
                await self.db.insert("btc_research_literature", payload)
                inserted += 1
            except Exception:
                pass

        await self.db.add_event(
            run_id,
            "LITERATURE_SCOUT_COMPLETE",
            {
                "topic": topic,
                "items": len(grounded),
                "inserted": inserted,
                "invalid_items": len(invalid),
                "invalid_examples": invalid[:3],
                "questionable_url_hosts": questionable[:5],
                "tool_source_count": len(out.sources),
                "tool_sources": out.sources[:50],
                "model": settings.openai_worker_model,
                "cost_usd": out.cost_usd,
                "parse_mode": parse_mode,
            },
        )
        return grounded

    async def source_count(self, run_id):
        return len(
            await self.db.select(
                "btc_research_literature", "id", limit=2000, run_id=run_id
            )
        )

    async def recent_sources(self, run_id, limit=120):
        return await self.db.select(
            "btc_research_literature",
            "id,title,url,quality_tier,research_question,claim,method,dataset_period,"
            "timeframe,costs_included,leakage_risks,replication_value,tags",
            limit=limit,
            order="created_at",
            descending=True,
            run_id=run_id,
        )

    async def synthesize_map(self, run_id):
        sources = json.dumps(
            await self.recent_sources(run_id, 160),
            ensure_ascii=False,
            default=str,
        )[:190000]
        system = (
            "You are a senior BTC quantitative literature synthesizer. Compress evidence "
            "without inventing consensus. Distinguish replicated evidence, contradictory "
            "evidence, methodological weaknesses, likely dead ends, and high-value "
            "replication gaps."
        )
        request = (
            "Build a compact research map from these records. Keep each list to at most "
            "8 concise findings and each finding under 280 characters. Do not overstate "
            "weak evidence.\n\nPRIOR RESEARCH RECORDS:\n"
            + sources
        )
        try:
            result, _ = await self.anthropic.ask_typed(
                output_format=LiteratureMap,
                run_id=run_id,
                role="literature_synthesizer",
                model=settings.anthropic_senior_model,
                system=system,
                prompt=request,
                max_tokens=4500,
                effort="high",
            )
            data = result.model_dump(mode="json")
            mode = "ANTHROPIC_STRUCTURED"
        except Exception as anthropic_error:
            await self._event(
                run_id,
                "PROVIDER_FAILOVER",
                {
                    "stage": "literature_map",
                    "from": "anthropic",
                    "to": "openai",
                    "error": str(anthropic_error)[:1000],
                },
            )
            try:
                result, _ = await self.openai.ask_typed(
                    output_format=LiteratureMap,
                    run_id=run_id,
                    role="literature_synthesizer_failover",
                    model=settings.openai_senior_model,
                    instructions=system,
                    prompt=request,
                    effort="high",
                    max_output_tokens=5000,
                    web_search=False,
                )
                data = result.model_dump(mode="json")
                mode = "OPENAI_STRUCTURED_FAILOVER"
            except Exception as openai_error:
                await self._event(
                    run_id,
                    "PROVIDER_FAILOVER_FAILED",
                    {
                        "stage": "literature_map",
                        "anthropic_error": str(anthropic_error)[:800],
                        "openai_error": str(openai_error)[:800],
                    },
                )
                memo = await self.anthropic.ask(
                    run_id=run_id,
                    role="literature_synthesizer_text_fallback",
                    model=settings.anthropic_senior_model,
                    system=system,
                    prompt=(
                        "Produce a concise plain-text research memo with six headings: "
                        "themes, replicated findings, contradictions, weak/invalid claims, "
                        "high-value replications, open questions. Keep the whole memo under "
                        "1800 tokens.\n\n"
                        + sources
                    ),
                    max_tokens=2200,
                    effort="medium",
                )
                data = {"parse_mode": "TEXT_FALLBACK", "memo": memo.text}
                mode = "TEXT_FALLBACK"
        await self.db.add_event(
            run_id, "LITERATURE_MAP", {"parse_mode": mode, "data": data}
        )
        return data

    async def propose_experiment(self, run_id, failure_memory, directive=""):
        sources = json.dumps(
            await self.recent_sources(run_id, 120), ensure_ascii=False, default=str
        )[:150000]
        failures = json.dumps(
            failure_memory[-50:], ensure_ascii=False, default=str
        )[:45000]
        request = (
            "RESEARCH DIRECTOR DIRECTIVE:\n"
            + (directive or "Replicate or extend the highest-information-value prior finding.")
            + "\n\nPRIOR RESEARCH DATABASE:\n"
            + sources
            + "\n\nFAILURE MEMORY:\n"
            + failures
            + "\n\nDesign exactly one compact, falsifiable ExperimentSpec."
        )
        try:
            spec, _ = await self.anthropic.ask_typed(
                output_format=ExperimentSpec,
                run_id=run_id,
                role="senior_researcher",
                model=settings.anthropic_senior_model,
                system=prompt("senior_researcher.md"),
                prompt=request,
                max_tokens=5000,
                effort="high",
            )
            return spec
        except Exception as anthropic_error:
            await self._event(
                run_id,
                "PROVIDER_FAILOVER",
                {
                    "stage": "experiment_spec",
                    "from": "anthropic",
                    "to": "openai",
                    "error": str(anthropic_error)[:1000],
                },
            )
            spec, _ = await self.openai.ask_typed(
                output_format=ExperimentSpec,
                run_id=run_id,
                role="senior_researcher_failover",
                model=settings.openai_senior_model,
                instructions=prompt("senior_researcher.md"),
                prompt=request,
                effort="high",
                max_output_tokens=6000,
                web_search=False,
            )
            return spec
