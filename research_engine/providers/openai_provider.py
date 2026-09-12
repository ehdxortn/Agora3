from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel

from ..config import settings
from ..models import DirectorDecision

OPENAI_PRICE = {
    "gpt-5.6-sol": (4.0, 20.0),
    "gpt-5.6": (4.0, 20.0),
    "gpt-5.6-terra": (2.0, 12.0),
    "gpt-5.6-luna": (0.20, 1.20),
}
WEB_SEARCH_USD_PER_CALL = 0.01
T = TypeVar("T", bound=BaseModel)


@dataclass
class ModelOutput:
    text: str
    input_tokens: int
    output_tokens: int
    web_searches: int
    cost_usd: float
    raw_id: str | None = None
    sources: list[str] = field(default_factory=list)
    status: str | None = None


def _json(text: str):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as first_error:
        decoder = json.JSONDecoder()
        for index, char in enumerate(text):
            if char not in "[{":
                continue
            try:
                value, _ = decoder.raw_decode(text[index:])
                return value
            except json.JSONDecodeError:
                continue
        raise ValueError("OpenAI response did not contain complete JSON") from first_error


class OpenAIProvider:
    def __init__(self, db):
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required")
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.db = db

    @staticmethod
    def estimate_cost(model, input_tokens, output_tokens, web_searches=0):
        input_price, output_price = OPENAI_PRICE.get(model, (4.0, 20.0))
        return (
            input_tokens / 1e6 * input_price
            + output_tokens / 1e6 * output_price
            + web_searches * WEB_SEARCH_USD_PER_CALL
        )

    @staticmethod
    def _web_metadata(response):
        searches = 0
        sources: list[str] = []
        for item in (getattr(response, "output", []) or []):
            if getattr(item, "type", None) != "web_search_call":
                continue
            searches += 1
            action = getattr(item, "action", None)
            for source in (getattr(action, "sources", []) or []):
                url = source.get("url") if isinstance(source, dict) else getattr(source, "url", None)
                if url and url not in sources:
                    sources.append(url)
        return searches, sources

    async def _record_response(self, response, *, run_id, role, model):
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        searches, sources = self._web_metadata(response)
        cost = self.estimate_cost(model, input_tokens, output_tokens, searches)
        await self.db.record_cost(
            run_id,
            "openai",
            model,
            role,
            input_tokens,
            output_tokens,
            searches,
            cost,
            {"web_sources": sources[:200]},
        )
        return ModelOutput(
            text=getattr(response, "output_text", "") or "",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            web_searches=searches,
            cost_usd=cost,
            raw_id=getattr(response, "id", None),
            sources=sources,
            status=getattr(response, "status", None),
        )

    @staticmethod
    def _request_kwargs(*, model, instructions, prompt, effort, max_output_tokens, web_search):
        kwargs = {
            "model": model,
            "instructions": instructions,
            "input": prompt,
            "max_output_tokens": max_output_tokens,
            "store": False,
            "reasoning": {"effort": effort},
        }
        if web_search:
            kwargs["tools"] = [{"type": "web_search_preview", "search_context_size": "medium"}]
            kwargs["include"] = ["web_search_call.action.sources"]
            kwargs["max_tool_calls"] = settings.max_web_search_calls
        return kwargs

    async def ask(self, *, run_id, role, model, instructions, prompt, effort="medium", max_output_tokens=6000, web_search=False):
        response = await self.client.responses.create(
            **self._request_kwargs(
                model=model,
                instructions=instructions,
                prompt=prompt,
                effort=effort,
                max_output_tokens=max_output_tokens,
                web_search=web_search,
            )
        )
        return await self._record_response(response, run_id=run_id, role=role, model=model)

    async def ask_typed(self, *, output_format: type[T], run_id, role, model, instructions, prompt, effort="medium", max_output_tokens=6000, web_search=False) -> tuple[T, ModelOutput]:
        last_error: Exception | None = None
        for attempt in range(2):
            token_limit = max_output_tokens if attempt == 0 else min(16000, max(8000, max_output_tokens * 2))
            retry_prompt = prompt if attempt == 0 else prompt + "\n\nReturn the requested structured object completely and concisely. Shorten prose rather than truncating required fields."
            try:
                response = await self.client.responses.parse(
                    **self._request_kwargs(
                        model=model,
                        instructions=instructions,
                        prompt=retry_prompt,
                        effort=effort,
                        max_output_tokens=token_limit,
                        web_search=web_search,
                    ),
                    text_format=output_format,
                )
                out = await self._record_response(response, run_id=run_id, role=role, model=model)
                parsed = getattr(response, "output_parsed", None)
                if parsed is not None:
                    return parsed, out
                last_error = RuntimeError(f"OpenAI structured output missing parsed result; status={out.status}")
            except Exception as exc:
                last_error = exc
            try:
                await self.db.add_event(run_id, "OPENAI_TYPED_RETRY", {"role": role, "model": model, "attempt": attempt + 1, "error": str(last_error)[:800]})
            except Exception:
                pass
        raise RuntimeError(f"OpenAI structured output failed twice for role={role}: {last_error}") from last_error

    async def ask_json(self, **kwargs):
        # The director is a safety-critical control decision. Use the SDK's native
        # structured-output contract rather than parsing free-form JSON text.
        if kwargs.get("role") == "research_director":
            parsed, out = await self.ask_typed(output_format=DirectorDecision, **kwargs)
            return parsed.model_dump(mode="json"), out
        out = await self.ask(**kwargs)
        return _json(out.text), out
