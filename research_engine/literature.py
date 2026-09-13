from __future__ import annotations

import json
import re
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

_STOPWORDS = {
    "btc", "bitcoin", "crypto", "cryptocurrency", "research", "evidence", "return",
    "returns", "trading", "strategy", "strategies", "study", "studies", "market",
    "markets", "forward", "subsequent", "using", "with", "after", "from", "into",
    "and", "the", "for", "that", "this", "only", "current", "prior", "art",
}


def prompt(name):
    return (P / name).read_text(encoding="utf-8")


def _hostname(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _terms(value) -> set[str]:
    text = str(value or "").lower()
    return {
        x for x in re.findall(r"[a-z0-9_\-]+", text)
        if len(x) >= 3 and x not in _STOPWORDS
    }


def _record_score(row: dict, query: str) -> float:
    q = _terms(query)
    if not q:
        return 0.0
    weighted = [
        ("title", 4.0), ("topic", 3.0), ("tags", 3.0),
        ("research_question", 2.0), ("claim", 2.0), ("method", 1.0),
    ]
    overlap = 0.0
    for key, weight in weighted:
        value = row.get(key)
        if isinstance(value, (list, dict)):
            value = json.dumps(value, ensure_ascii=False)
        overlap += weight * len(q & _terms(value))
    if overlap <= 0:
        return 0.0
    if row.get("quality_tier") == "A":
        overlap += 2.0
    elif row.get("quality_tier") == "B":
        overlap += 1.0
    if row.get("replication_value") == "HIGH":
        overlap += 1.0
    return overlap


def _compact_failure(row: dict) -> dict:
    spec = row.get("spec") or {}
    result = row.get("result") or {}
    def metrics(name):
        m = result.get(name) or {}
        return {
            "trades": m.get("trades"),
            "mean_net_return": m.get("mean_net_return"),
            "profit_factor": m.get("profit_factor"),
            "max_drawdown": m.get("max_drawdown"),
        }
    return {
        "spec_hash": row.get("spec_hash"),
        "hypothesis": row.get("hypothesis"),
        "status": row.get("status"),
        "rejection_reason": (row.get("rejection_reason") or "")[:1000],
        "side": spec.get("side"),
        "features": [
            {
                "family": x.get("family"), "lookback": x.get("lookback"),
                "column": x.get("column"), "fast": x.get("fast"), "slow": x.get("slow"),
            }
            for x in (spec.get("features") or [])[:8]
        ],
        "conditions": (spec.get("conditions") or [])[:8],
        "exit": spec.get("exit"),
        "train": metrics("train"),
        "validation": metrics("validation"),
        "robustness": result.get("robustness") or result.get("walk_forward") or {},
    }


def _failure_score(row: dict, query: str) -> float:
    q = _terms(query)
    if not q:
        return 0.0
    spec = row.get("spec") or {}
    text = " ".join([
        str(row.get("hypothesis") or ""),
        str(row.get("rejection_reason") or ""),
        json.dumps(spec.get("features") or [], ensure_ascii=False),
        json.dumps(spec.get("conditions") or [], ensure_ascii=False),
    ])
    return float(len(q & _terms(text)))


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

    async def all_sources(self, limit=3000):
        return await self.db.select(
            "btc_research_literature",
            "id,run_id,topic,title,url,quality_tier,source_type,published_date,"
            "research_question,claim,method,dataset_period,timeframe,costs_included,"
            "leakage_risks,replication_value,tags,created_at",
            limit=limit,
            order="created_at",
            descending=True,
        )

    async def source_count(self, run_id=None):
        rows = await self.db.select(
            "btc_research_literature", "id,url", limit=5000
        )
        return len({r.get("url") or r.get("id") for r in rows})

    async def retrieve_sources(self, query: str, limit=None):
        limit = limit or settings.literature_retrieval_limit
        rows = await self.all_sources()
        scored = []
        for row in rows:
            score = _record_score(row, query)
            if score > 0:
                scored.append((score, row))
        scored.sort(key=lambda x: (x[0], x[1].get("created_at") or ""), reverse=True)
        out, seen = [], set()
        for score, row in scored:
            url = row.get("url") or str(row.get("id"))
            if url in seen:
                continue
            seen.add(url)
            item = dict(row)
            item["retrieval_score"] = score
            out.append(item)
            if len(out) >= limit:
                break
        return out

    async def best_sources(self, limit=None):
        limit = limit or settings.literature_retrieval_limit
        rows = await self.all_sources()
        tier = {"A": 3, "B": 2, "C": 1}
        rep = {"HIGH": 2, "MEDIUM": 1, "LOW": 0}
        rows.sort(
            key=lambda r: (
                tier.get(r.get("quality_tier"), 0),
                rep.get(r.get("replication_value"), 0),
                r.get("created_at") or "",
            ),
            reverse=True,
        )
        out, seen = [], set()
        for row in rows:
            url = row.get("url") or str(row.get("id"))
            if url in seen:
                continue
            seen.add(url)
            out.append(row)
            if len(out) >= limit:
                break
        return out

    async def ensure_topic_coverage(self, run_id, topic):
        existing = await self.retrieve_sources(topic, limit=max(settings.topic_reuse_min_sources, settings.literature_retrieval_limit))
        if len(existing) >= settings.topic_reuse_min_sources:
            await self._event(
                run_id,
                "LITERATURE_MEMORY_REUSED",
                {
                    "topic": topic,
                    "matched_sources": len(existing),
                    "source_ids": [str(x.get("id")) for x in existing[:settings.literature_retrieval_limit]],
                    "saved_web_search": True,
                },
            )
            return existing
        return await self.scout_topic(run_id, topic)

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
                prompt=(worker_prompt + "\n\nReturn one JSON object with exactly one key 'items'."),
                effort="low",
                max_output_tokens=6500,
                web_search=True,
            )
            raw_items = data.get("items", []) if isinstance(data, dict) else data
            if not isinstance(raw_items, list):
                raw_items = [raw_items]
            items, invalid = [], []
            for index, raw in enumerate(raw_items):
                try:
                    items.append(LiteratureItem.model_validate(raw))
                except Exception as exc:
                    invalid.append({"index": index, "error": str(exc)[:1200]})

        source_hosts = {_hostname(url) for url in out.sources if _hostname(url)}
        grounded, questionable = [], []
        for item in items:
            item_host = _hostname(item.url)
            if source_hosts and item_host and item_host not in source_hosts:
                questionable.append({"title": item.title[:180], "url": item.url})
            grounded.append(item)

        inserted, reused = 0, 0
        for item in grounded:
            prior = await self.db.select("btc_research_literature", "id", limit=1, url=item.url)
            if prior:
                reused += 1
                continue
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
                "topic": topic, "items": len(grounded), "inserted": inserted,
                "reused_existing_urls": reused, "invalid_items": len(invalid),
                "invalid_examples": invalid[:3], "questionable_url_hosts": questionable[:5],
                "tool_source_count": len(out.sources), "tool_sources": out.sources[:50],
                "model": settings.openai_worker_model, "cost_usd": out.cost_usd,
                "parse_mode": parse_mode,
            },
        )
        return grounded

    async def recent_sources(self, run_id=None, limit=120):
        rows = await self.all_sources(limit=max(limit, 300))
        return rows[:limit]

    async def _cached_map(self, current_count):
        events = await self.db.select(
            "btc_research_events", "payload,created_at", limit=8,
            order="created_at", descending=True, event_type="LITERATURE_MAP_CACHE"
        )
        for event in events:
            payload = event.get("payload") or {}
            cached_count = int(payload.get("source_count") or 0)
            data = payload.get("data")
            if data and current_count - cached_count < settings.literature_map_refresh_delta:
                return data, cached_count
        # Import a legacy map only when it is newer than the newest literature record.
        legacy = await self.db.select(
            "btc_research_events", "payload,created_at", limit=1,
            order="created_at", descending=True, event_type="LITERATURE_MAP"
        )
        newest = await self.db.select(
            "btc_research_literature", "created_at", limit=1,
            order="created_at", descending=True
        )
        if legacy and newest and (legacy[0].get("created_at") or "") >= (newest[0].get("created_at") or ""):
            data = (legacy[0].get("payload") or {}).get("data")
            if data:
                return data, current_count
        return None, 0

    async def synthesize_map(self, run_id):
        current_count = await self.source_count()
        cached, cached_count = await self._cached_map(current_count)
        if cached:
            await self._event(
                run_id, "LITERATURE_MAP_REUSED",
                {"source_count": current_count, "cached_source_count": cached_count, "saved_senior_call": True}
            )
            return cached

        rows = await self.best_sources(limit=60)
        sources = json.dumps(rows, ensure_ascii=False, default=str)[:70000]
        system = (
            "You are a senior BTC quantitative literature synthesizer. Compress evidence "
            "without inventing consensus. Distinguish replicated evidence, contradictory "
            "evidence, methodological weaknesses, likely dead ends, and high-value replication gaps."
        )
        request = (
            "Build a compact research map from these highest-value records. Keep each list to at most "
            "8 concise findings and each finding under 280 characters. Do not overstate weak evidence.\n\n"
            + sources
        )
        try:
            result, _ = await self.anthropic.ask_typed(
                output_format=LiteratureMap, run_id=run_id, role="literature_synthesizer",
                model=settings.anthropic_senior_model, system=system, prompt=request,
                max_tokens=3500, effort="high",
            )
            data = result.model_dump(mode="json")
            mode = "ANTHROPIC_STRUCTURED"
        except Exception as anthropic_error:
            await self._event(run_id, "PROVIDER_FAILOVER", {"stage": "literature_map", "from": "anthropic", "to": "openai", "error": str(anthropic_error)[:1000]})
            try:
                result, _ = await self.openai.ask_typed(
                    output_format=LiteratureMap, run_id=run_id, role="literature_synthesizer_failover",
                    model=settings.openai_senior_model, instructions=system, prompt=request,
                    effort="high", max_output_tokens=4000, web_search=False,
                )
                data = result.model_dump(mode="json")
                mode = "OPENAI_STRUCTURED_FAILOVER"
            except Exception as openai_error:
                await self._event(run_id, "PROVIDER_FAILOVER_FAILED", {"stage": "literature_map", "anthropic_error": str(anthropic_error)[:800], "openai_error": str(openai_error)[:800]})
                memo = await self.anthropic.ask(
                    run_id=run_id, role="literature_synthesizer_text_fallback",
                    model=settings.anthropic_senior_model, system=system,
                    prompt="Produce a concise research memo under 1500 tokens.\n\n" + sources,
                    max_tokens=1800, effort="medium",
                )
                data = {"parse_mode": "TEXT_FALLBACK", "memo": memo.text}
                mode = "TEXT_FALLBACK"
        payload = {"parse_mode": mode, "source_count": current_count, "data": data}
        await self.db.add_event(run_id, "LITERATURE_MAP", payload)
        await self.db.add_event(run_id, "LITERATURE_MAP_CACHE", payload)
        return data

    def relevant_failures(self, failure_memory, directive):
        scored = [(_failure_score(x, directive), x) for x in failure_memory]
        relevant = [x for score, x in sorted(scored, key=lambda p: p[0], reverse=True) if score > 0]
        if len(relevant) < settings.failure_retrieval_limit:
            seen = {x.get("spec_hash") for x in relevant}
            for row in failure_memory:
                if row.get("spec_hash") in seen:
                    continue
                relevant.append(row)
                seen.add(row.get("spec_hash"))
                if len(relevant) >= settings.failure_retrieval_limit:
                    break
        return [_compact_failure(x) for x in relevant[:settings.failure_retrieval_limit]]

    async def propose_experiment(self, run_id, failure_memory, directive=""):
        query = directive or "replication causal volatility momentum funding open interest microstructure"
        sources = await self.retrieve_sources(query, limit=settings.literature_retrieval_limit)
        if len(sources) < max(4, settings.topic_reuse_min_sources // 2):
            fallback = await self.best_sources(limit=settings.literature_retrieval_limit)
            seen = {x.get("url") for x in sources}
            sources += [x for x in fallback if x.get("url") not in seen][: settings.literature_retrieval_limit - len(sources)]
        source_packet = [
            {
                "id": str(x.get("id")), "title": x.get("title"), "quality_tier": x.get("quality_tier"),
                "research_question": x.get("research_question"), "claim": x.get("claim"),
                "method": x.get("method"), "dataset_period": x.get("dataset_period"),
                "timeframe": x.get("timeframe"), "costs_included": x.get("costs_included"),
                "leakage_risks": x.get("leakage_risks"), "replication_value": x.get("replication_value"),
                "tags": x.get("tags"),
            }
            for x in sources
        ]
        failures = self.relevant_failures(failure_memory, query)
        request = (
            "RESEARCH DIRECTOR DIRECTIVE:\n" + (directive or "Replicate or extend the highest-information-value prior finding.")
            + "\n\nRETRIEVED PRIOR RESEARCH (use these ids; do not ask for the full database):\n"
            + json.dumps(source_packet, ensure_ascii=False, default=str)[:35000]
            + "\n\nMOST RELEVANT FAILURE MEMORY (compressed):\n"
            + json.dumps(failures, ensure_ascii=False, default=str)[:22000]
            + "\n\nDesign exactly one compact, falsifiable ExperimentSpec. Reuse existing evidence instead of requesting new web research unless the retrieved packet is genuinely insufficient."
        )
        await self._event(
            run_id, "RESEARCH_MEMORY_PACKET",
            {
                "retrieved_source_count": len(source_packet), "failure_count": len(failures),
                "source_ids": [x["id"] for x in source_packet], "web_search_used": False,
            },
        )
        try:
            spec, _ = await self.anthropic.ask_typed(
                output_format=ExperimentSpec, run_id=run_id, role="senior_researcher",
                model=settings.anthropic_senior_model, system=prompt("senior_researcher.md"),
                prompt=request, max_tokens=4200, effort="high",
            )
            return spec
        except Exception as anthropic_error:
            await self._event(run_id, "PROVIDER_FAILOVER", {"stage": "experiment_spec", "from": "anthropic", "to": "openai", "error": str(anthropic_error)[:1000]})
            spec, _ = await self.openai.ask_typed(
                output_format=ExperimentSpec, run_id=run_id, role="senior_researcher_failover",
                model=settings.openai_senior_model, instructions=prompt("senior_researcher.md"),
                prompt=request, effort="high", max_output_tokens=5000, web_search=False,
            )
            return spec
