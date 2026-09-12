from __future__ import annotations
import os
from dataclasses import dataclass

def _env(name,default=None,required=False):
 v=os.getenv(name,default)
 if v is not None:v=v.strip()
 if required and not v:raise RuntimeError(f"Missing required environment variable: {name}")
 return v
def _float(name,default):return float(_env(name,str(default)) or default)
def _int(name,default):return int(_env(name,str(default)) or default)
@dataclass(frozen=True)
class Settings:
 openai_api_key:str|None=_env("OPENAI_API_KEY");anthropic_api_key:str|None=_env("ANTHROPIC_API_KEY");supabase_url:str|None=_env("SUPABASE_URL");supabase_service_role_key:str|None=_env("SUPABASE_SERVICE_ROLE_KEY")
 openai_director_model:str=_env("OPENAI_DIRECTOR_MODEL","gpt-5.6-sol") or "gpt-5.6-sol";openai_senior_model:str=_env("OPENAI_SENIOR_MODEL","gpt-5.6-terra") or "gpt-5.6-terra";openai_worker_model:str=_env("OPENAI_WORKER_MODEL","gpt-5.6-luna") or "gpt-5.6-luna";anthropic_senior_model:str=_env("ANTHROPIC_SENIOR_MODEL","claude-sonnet-5") or "claude-sonnet-5";anthropic_critic_model:str=_env("ANTHROPIC_CRITIC_MODEL","claude-opus-5") or "claude-opus-5"
 daily_budget_usd:float=_float("DAILY_BUDGET_USD",15.0);run_budget_usd:float=_float("RUN_BUDGET_USD",10.0);max_cycles_per_job:int=_int("MAX_CYCLES_PER_JOB",100);literature_min_sources:int=_int("LITERATURE_MIN_SOURCES",120);max_holdout_evaluations:int=_int("MAX_HOLDOUT_EVALUATIONS",12);max_web_search_calls:int=_int("MAX_WEB_SEARCH_CALLS",8);round_trip_fee_bps:float=_float("ROUND_TRIP_FEE_BPS",8.0);slippage_bps:float=_float("SLIPPAGE_BPS",2.0);min_oos_trades:int=_int("MIN_OOS_TRADES",80);max_drawdown_gate:float=_float("MAX_DRAWDOWN_GATE",0.25);onchain_lag_days:int=_int("ONCHAIN_LAG_DAYS",2)
 api_secret:str|None=_env("RESEARCH_API_SECRET");environment:str=_env("ENVIRONMENT","dev") or "dev"
 @property
 def all_in_cost_rate(self):return (self.round_trip_fee_bps+self.slippage_bps)/10000.0
settings=Settings()
