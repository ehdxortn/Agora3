from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TypeVar

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from ..config import settings

ANTHROPIC_PRICE = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}
T = TypeVar("T", bound=BaseModel)


def _extract_json(text: str):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as first_error:
        decoder = json.JSONDecoder()
        for i, ch in enumerate(text):
            if ch not in "[{":
                continue
            try:
                value, _ = decoder.raw_decode(text[i:])
                return value
            except json.JSONDecodeError:
                continue
        raise ValueError(
            "Anthropic response did not contain a complete valid JSON value"
        ) from first_error


@dataclass
class ModelOutput:
    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    raw_id: str | None = None
    stop_reason: str | None = None


class AnthropicProvider:
    def __init__(self, db):
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required")
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.db = db

    @staticmethod
    def estimate_cost(model, input_tokens, output_tokens):
        input_price, output_price = ANTHROPIC_PRICE.get(model, (5.0, 25.0))
        return input_tokens / 1e6 * input_price + output_tokens / 1e6 * output_price

    async def _record_response(self, response, *, run_id, role, model):
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        text = "\n".join(
            block.text
            for block in (getattr(response, "content", []) or [])
            if getattr(block, "type", None) == "text"
        )
        cost = self.estimate_cost(model, input_tokens, output_tokens)
        await self.db.record_cost(
            run_id,
            "anthropic",
            model,
            role,
            input_tokens,
            output_tokens,
            0,
            cost,
        )
        return ModelOutput(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            raw_id=getattr(response, "id", None),
            stop_reason=getattr(response, "stop_reason", None),
        )

    async def _event(self, run_id, event_type, payload):
        try:
            await self.db.add_event(run_id, event_type, payload)
        except Exception:
            pass

    async def ask(
        self,
        *,
        run_id,
        role,
        model,
        system,
        prompt,
        max_tokens=6000,
        effort="high",
    ):
        response = await self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": effort},
        )
        return await self._record_response(
            response, run_id=run_id, role=role, model=model
        )

    async def ask_typed(
        self,
        *,
        output_format: type[T],
        run_id,
        role,
        model,
        system,
        prompt,
        max_tokens=6000,
        effort="high",
    ) -> tuple[T, ModelOutput]:
        last_error: Exception | None = None
        for attempt in range(2):
            token_limit = (
                max_tokens
                if attempt == 0
                else min(16000, max(8000, max_tokens * 2))
            )
            retry_prompt = prompt
            if attempt:
                retry_prompt += (
                    "\n\nBe concise and complete the structured response before the output "
                    "limit. Shorten explanatory strings rather than omitting required fields."
                )
            try:
                response = await self.client.messages.parse(
                    model=model,
                    max_tokens=token_limit,
                    system=system,
                    messages=[{"role": "user", "content": retry_prompt}],
                    output_config={"effort": effort},
                    output_format=output_format,
                )
                out = await self._record_response(
                    response, run_id=run_id, role=role, model=model
                )
                parsed = getattr(response, "parsed_output", None)
                if parsed is not None:
                    return parsed, out
                last_error = RuntimeError(
                    "Anthropic structured output missing parsed_output; "
                    f"stop_reason={out.stop_reason}"
                )
            except Exception as exc:
                last_error = exc
            await self._event(
                run_id,
                "ANTHROPIC_TYPED_RETRY",
                {
                    "role": role,
                    "model": model,
                    "attempt": attempt + 1,
                    "error": str(last_error)[:800],
                },
            )
        raise RuntimeError(
            f"Anthropic structured output failed twice for role={role}: {last_error}"
        ) from last_error

    async def ask_json(self, **kwargs):
        out = await self.ask(**kwargs)
        try:
            return _extract_json(out.text), out
        except (ValueError, json.JSONDecodeError) as first:
            await self._event(
                kwargs.get("run_id"),
                "ANTHROPIC_JSON_PARSE_RETRY",
                {
                    "role": kwargs.get("role"),
                    "model": kwargs.get("model"),
                    "stop_reason": out.stop_reason,
                    "output_tokens": out.output_tokens,
                    "text_chars": len(out.text),
                    "error": str(first)[:500],
                },
            )
            retry = dict(kwargs)
            retry["prompt"] = (
                str(kwargs.get("prompt") or "")
                + "\n\nReturn ONLY one complete valid JSON value. No markdown or prose. "
                "Be concise and close the JSON before the output limit."
            )
            original_max = int(kwargs.get("max_tokens", 6000) or 6000)
            retry["max_tokens"] = min(16000, max(8000, original_max * 2))
            out2 = await self.ask(**retry)
            try:
                return _extract_json(out2.text), out2
            except (ValueError, json.JSONDecodeError) as exc:
                await self._event(
                    kwargs.get("run_id"),
                    "ANTHROPIC_JSON_PARSE_FAILED",
                    {
                        "role": kwargs.get("role"),
                        "model": kwargs.get("model"),
                        "stop_reason": out2.stop_reason,
                        "output_tokens": out2.output_tokens,
                        "text_chars": len(out2.text),
                        "error": str(exc)[:500],
                    },
                )
                raise RuntimeError(
                    "Anthropic returned invalid or incomplete JSON twice"
                ) from exc
