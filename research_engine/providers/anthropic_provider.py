from __future__ import annotations
import json,re
from dataclasses import dataclass
from anthropic import AsyncAnthropic
from ..config import settings
ANTHROPIC_PRICE={"claude-opus-5":(5.0,25.0),"claude-sonnet-5":(2.0,10.0),"claude-haiku-4-5-20251001":(1.0,5.0)}

def _extract_json(text):
    text=(text or "").strip()
    if text.startswith("```"):
        text=re.sub(r"^```(?:json)?\s*","",text); text=re.sub(r"\s*```$","",text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as first_error:
        decoder=json.JSONDecoder()
        for i,ch in enumerate(text):
            if ch not in "[{":
                continue
            try:
                value,_=decoder.raw_decode(text[i:])
                return value
            except json.JSONDecodeError:
                continue
        raise ValueError("Anthropic response did not contain a complete valid JSON value") from first_error

@dataclass
class ModelOutput:
    text:str; input_tokens:int; output_tokens:int; cost_usd:float; raw_id:str|None=None
class AnthropicProvider:
    def __init__(self,db):
        if not settings.anthropic_api_key: raise RuntimeError("ANTHROPIC_API_KEY is required")
        self.client=AsyncAnthropic(api_key=settings.anthropic_api_key); self.db=db
    @staticmethod
    def estimate_cost(model,input_tokens,output_tokens):
        ip,op=ANTHROPIC_PRICE.get(model,(5.0,25.0)); return input_tokens/1e6*ip+output_tokens/1e6*op
    async def ask(self,*,run_id,role,model,system,prompt,max_tokens=6000,effort="high"):
        response=await self.client.messages.create(model=model,max_tokens=max_tokens,system=system,messages=[{"role":"user","content":prompt}],output_config={"effort":effort})
        text="\n".join(b.text for b in response.content if getattr(b,"type",None)=="text"); inp=int(getattr(response.usage,"input_tokens",0) or 0); out=int(getattr(response.usage,"output_tokens",0) or 0)
        cost=self.estimate_cost(model,inp,out); await self.db.record_cost(run_id,"anthropic",model,role,inp,out,0,cost)
        return ModelOutput(text,inp,out,cost,getattr(response,"id",None))
    async def ask_json(self,**kwargs):
        out=await self.ask(**kwargs)
        try:
            return _extract_json(out.text),out
        except (ValueError,json.JSONDecodeError):
            retry=dict(kwargs)
            retry["prompt"]=(str(kwargs.get("prompt") or "")+"\n\nIMPORTANT: Your previous response was not parseable as complete JSON. Return ONLY one complete valid JSON value matching the requested schema. No markdown fences, no prose before or after JSON, and do not truncate the JSON.")
            original_max=int(kwargs.get("max_tokens",6000) or 6000)
            retry["max_tokens"]=min(12000,max(original_max+1500,int(original_max*1.25)))
            out2=await self.ask(**retry)
            try:
                return _extract_json(out2.text),out2
            except (ValueError,json.JSONDecodeError) as exc:
                raise RuntimeError("Anthropic returned invalid JSON twice; aborting this model step") from exc
