from __future__ import annotations
import json,re
from dataclasses import dataclass,field
from openai import AsyncOpenAI
from ..config import settings
OPENAI_PRICE={"gpt-5.6-sol":(4.0,20.0),"gpt-5.6":(4.0,20.0),"gpt-5.6-terra":(2.0,12.0),"gpt-5.6-luna":(0.20,1.20)};WEB_SEARCH_USD_PER_CALL=.01
@dataclass
class ModelOutput:text:str;input_tokens:int;output_tokens:int;web_searches:int;cost_usd:float;raw_id:str|None=None;sources:list[str]=field(default_factory=list)
def _json(text):
 text=text.strip();text=re.sub(r"^```(?:json)?\s*","",text);text=re.sub(r"\s*```$","",text)
 try:return json.loads(text)
 except json.JSONDecodeError:
  starts=[p for p in (text.find("{"),text.find("[")) if p>=0]
  if not starts:raise
  return json.loads(text[min(starts):max(text.rfind("}"),text.rfind("]"))+1])
class OpenAIProvider:
 def __init__(self,db):
  if not settings.openai_api_key:raise RuntimeError("OPENAI_API_KEY is required")
  self.client=AsyncOpenAI(api_key=settings.openai_api_key);self.db=db
 @staticmethod
 def estimate_cost(model,i,o,w=0):
  ip,op=OPENAI_PRICE.get(model,(4.,20.));return i/1e6*ip+o/1e6*op+w*WEB_SEARCH_USD_PER_CALL
 async def ask(self,*,run_id,role,model,instructions,prompt,effort="medium",max_output_tokens=6000,web_search=False):
  kw={"model":model,"instructions":instructions,"input":prompt,"max_output_tokens":max_output_tokens,"store":False,"reasoning":{"effort":effort}}
  if web_search:kw["tools"]=[{"type":"web_search_preview","search_context_size":"medium"}];kw["include"]=["web_search_call.action.sources"];kw["max_tool_calls"]=settings.max_web_search_calls if hasattr(settings,"max_web_search_calls") else 8
  r=await self.client.responses.create(**kw);text=r.output_text or "";u=getattr(r,"usage",None);i=int(getattr(u,"input_tokens",0) or 0);o=int(getattr(u,"output_tokens",0) or 0);searches=0;sources=[]
  for item in (getattr(r,"output",[]) or []):
   if getattr(item,"type",None)=="web_search_call":
    searches+=1;action=getattr(item,"action",None)
    for s in (getattr(action,"sources",[]) or []):
     url=getattr(s,"url",None) if not isinstance(s,dict) else s.get("url")
     if url and url not in sources:sources.append(url)
  cost=self.estimate_cost(model,i,o,searches);await self.db.record_cost(run_id,"openai",model,role,i,o,searches,cost,{"web_sources":sources[:200]});return ModelOutput(text,i,o,searches,cost,getattr(r,"id",None),sources)
 async def ask_json(self,**kwargs):out=await self.ask(**kwargs);return _json(out.text),out
