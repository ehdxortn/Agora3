from __future__ import annotations
import json,re
from dataclasses import dataclass
from anthropic import AsyncAnthropic
from ..config import settings
ANTHROPIC_PRICE={"claude-opus-5":(5.0,25.0),"claude-sonnet-5":(2.0,10.0),"claude-haiku-4-5-20251001":(1.0,5.0)}

def _extract_json(text):
    text=text.strip()
    if text.startswith("```"):
        text=re.sub(r"^```(?:json)?\s*","",text); text=re.sub(r"\s*```$","",text)
    try:return json.loads(text)
    except json.JSONDecodeError:
        starts=[p for p in (text.find("{"),text.find("[")) if p>=0]
        if not starts: raise
        start=min(starts); end=max(text.rfind("}"),text.rfind("]")); return json.loads(text[start:end+1])
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
        out=await self.ask(**kwargs); return _extract_json(out.text),out
