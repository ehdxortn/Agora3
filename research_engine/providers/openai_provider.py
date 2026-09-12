from __future__ import annotations
import json,re
from dataclasses import dataclass
from typing import Any
from openai import AsyncOpenAI
from ..config import settings
from ..db import ResearchDB
OPENAI_PRICE={"gpt-5.6-sol":(4.0,20.0),"gpt-5.6":(4.0,20.0),"gpt-5.6-terra":(2.0,12.0),"gpt-5.6-luna":(0.20,1.20)}
WEB_SEARCH_USD_PER_CALL=0.01
@dataclass
class ModelOutput:
    text:str; input_tokens:int; output_tokens:int; web_searches:int; cost_usd:float; raw_id:str|None=None

def _extract_json(text):
    text=text.strip()
    if text.startswith("```"):
        text=re.sub(r"^```(?:json)?\s*","",text); text=re.sub(r"\s*```$","",text)
    try:return json.loads(text)
    except json.JSONDecodeError:
        starts=[p for p in (text.find("{"),text.find("[")) if p>=0]
        if not starts: raise
        start=min(starts); end=max(text.rfind("}"),text.rfind("]"))
        return json.loads(text[start:end+1])
class OpenAIProvider:
    def __init__(self,db):
        if not settings.openai_api_key: raise RuntimeError("OPENAI_API_KEY is required")
        self.client=AsyncOpenAI(api_key=settings.openai_api_key); self.db=db
    @staticmethod
    def estimate_cost(model,input_tokens,output_tokens,web_searches=0):
        ip,op=OPENAI_PRICE.get(model,(4.0,20.0)); return input_tokens/1e6*ip+output_tokens/1e6*op+web_searches*WEB_SEARCH_USD_PER_CALL
    async def ask(self,*,run_id,role,model,instructions,prompt,effort="medium",max_output_tokens=6000,web_search=False):
        kwargs={"model":model,"instructions":instructions,"input":prompt,"max_output_tokens":max_output_tokens,"store":False,"reasoning":{"effort":effort}}
        if web_search:
            kwargs["tools"]=[{"type":"web_search_preview","search_context_size":"medium"}]; kwargs["include"]=["web_search_call.action.sources"]; kwargs["max_tool_calls"]=settings.max_web_search_calls
        response=await self.client.responses.create(**kwargs); text=response.output_text or ""; usage=getattr(response,"usage",None)
        inp=int(getattr(usage,"input_tokens",0) or 0); out=int(getattr(usage,"output_tokens",0) or 0)
        searches=sum(1 for item in (getattr(response,"output",[]) or []) if getattr(item,"type",None)=="web_search_call")
        cost=self.estimate_cost(model,inp,out,searches); await self.db.record_cost(run_id,"openai",model,role,inp,out,searches,cost)
        return ModelOutput(text,inp,out,searches,cost,getattr(response,"id",None))
    async def ask_json(self,**kwargs):
        out=await self.ask(**kwargs); return _extract_json(out.text),out
