from __future__ import annotations
from datetime import datetime,timezone
from enum import Enum
from typing import Any,Literal
from pydantic import BaseModel,Field,model_validator

class Confidence(str,Enum):
 REJECTED="REJECTED"; WEAK="WEAK"; CANDIDATE="CANDIDATE"; ROBUST_CANDIDATE="ROBUST_CANDIDATE"; PRODUCTION_CANDIDATE="PRODUCTION_CANDIDATE"
class FeatureSpec(BaseModel):
 name:str=Field(min_length=1,max_length=80)
 family:Literal["price_return","ema_gap","rsi","atr_pct","realized_vol","volume_zscore","oi_change","oi_zscore","funding_mean","funding_zscore","taker_imbalance","ls_ratio_zscore","onchain_zscore"]
 lookback:int=Field(default=14,ge=1,le=720); column:str|None=None; fast:int|None=Field(default=None,ge=1,le=720); slow:int|None=Field(default=None,ge=2,le=1440)
class ConditionSpec(BaseModel):
 feature:str; op:Literal["gt","gte","lt","lte"]; threshold_type:Literal["absolute","train_quantile"]="absolute"; value:float
 @model_validator(mode="after")
 def q(self):
  if self.threshold_type=="train_quantile" and not 0<self.value<1: raise ValueError("train_quantile value must be between 0 and 1")
  return self
class ExitSpec(BaseModel):
 mode:Literal["fixed_horizon","stop_target"]="fixed_horizon"; horizon_bars:int=Field(default=3,ge=1,le=42); stop_loss_pct:float|None=Field(default=None,gt=0,le=.5); take_profit_pct:float|None=Field(default=None,gt=0,le=2)
 @model_validator(mode="after")
 def st(self):
  if self.mode=="stop_target" and (self.stop_loss_pct is None or self.take_profit_pct is None): raise ValueError("stop_target requires stop and target")
  return self
class ExperimentSpec(BaseModel):
 hypothesis:str=Field(min_length=20,max_length=2000); mechanism:str=Field(min_length=20,max_length=4000); side:Literal["long","short"]
 features:list[FeatureSpec]=Field(min_length=1,max_length=12); conditions:list[ConditionSpec]=Field(min_length=1,max_length=12); exit:ExitSpec=Field(default_factory=ExitSpec)
 train_fraction:float=Field(default=.60,ge=.4,le=.8); validation_fraction:float=Field(default=.20,ge=.1,le=.3); embargo_bars:int=Field(default=6,ge=0,le=84); fee_bps:float=Field(default=8,ge=0,le=100); slippage_bps:float=Field(default=2,ge=0,le=100); source_research_ids:list[str]=Field(default_factory=list,max_length=30); novelty_note:str=""
 @model_validator(mode="after")
 def valid(self):
  if self.train_fraction+self.validation_fraction>=.95: raise ValueError("Need at least 5% untouched test data")
  names={f.name for f in self.features}; missing=[c.feature for c in self.conditions if c.feature not in names]
  if missing: raise ValueError(f"Undefined features: {missing}")
  return self
class SplitMetrics(BaseModel):
 observations:int=0; trades:int=0; win_rate:float|None=None; mean_net_return:float|None=None; median_net_return:float|None=None; profit_factor:float|None=None; max_drawdown:float|None=None; cumulative_return:float|None=None; sharpe_like:float|None=None
class ExperimentResult(BaseModel):
 experiment_id:str; spec_hash:str; train:SplitMetrics; validation:SplitMetrics; test:SplitMetrics; parameter_stability:dict[str,Any]=Field(default_factory=dict); methodological_flags:list[str]=Field(default_factory=list); passed_minimum_gate:bool=False; generated_at:datetime=Field(default_factory=lambda:datetime.now(timezone.utc))
class LiteratureItem(BaseModel):
 title:str; url:str; source_type:Literal["peer_reviewed","preprint","institutional","exchange","github","blog","interview","other"]; quality_tier:Literal["A","B","C"]; published_date:str|None=None; research_question:str; claim:str; method:str; dataset_period:str|None=None; timeframe:str|None=None; costs_included:bool|None=None; leakage_risks:list[str]=Field(default_factory=list); replication_value:Literal["HIGH","MEDIUM","LOW"]="MEDIUM"; tags:list[str]=Field(default_factory=list)
class DirectorDecision(BaseModel):
 research_status:Literal["CONTINUE","COMPLETE","BLOCKED"]; confidence:Confidence; interpretation:str; critic_questions:list[str]=Field(default_factory=list); next_action:Literal["LITERATURE","REPLICATION","EXPERIMENT","ROBUSTNESS","PROMOTE","STOP"]; next_experiment:ExperimentSpec|None=None; reason_for_next_action:str
class PromotionPackage(BaseModel):
 contract_version:Literal["1.0"]="1.0"; research_run_id:str; experiment_id:str; signal_name:str; asset:Literal["BTC"]="BTC"; timeframe:Literal["4h"]="4h"; decision_time:Literal["candle_close"]="candle_close"; entry_time:Literal["next_candle_open"]="next_candle_open"; experiment_spec:ExperimentSpec; validated_metrics:ExperimentResult; feature_contract:dict[str,Any]; execution_contract:dict[str,Any]; data_contract:dict[str,Any]; code_version:str; prompt_version:str; status:Literal["PENDING_PARITY","PARITY_PASSED","SHADOW_APPROVED","REJECTED"]="PENDING_PARITY"; created_at:datetime=Field(default_factory=lambda:datetime.now(timezone.utc))
class StartRunRequest(BaseModel):
 mission:str="Discover repeatable, causal, economically exploitable Bitcoin trading edges that remain positive after realistic fees and slippage and survive chronological out-of-sample validation."
 budget_usd:float|None=Field(default=None,gt=0,le=1000); notes:str=""
