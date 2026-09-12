from __future__ import annotations
import hashlib,json,os
from .models import PromotionPackage
class PromotionManager:
 def __init__(self,db):self.db=db
 @staticmethod
 def feature(spec):return {"decision_clock":"completed BTCUSDT 4H candle close","entry_clock":"next BTCUSDT 4H candle open","features":[f.model_dump() for f in spec.features],"conditions":[c.model_dump() for c in spec.conditions],"no_future_data":True,"onchain_lag":"previous completed UTC day or older","threshold_training":"train split only for train_quantile thresholds"}
 @staticmethod
 def execution(spec):return {"side":spec.side,"entry":"next_candle_open","exit":spec.exit.model_dump(),"fee_bps":spec.fee_bps,"slippage_bps":spec.slippage_bps,"same_bar_stop_target_rule":"STOP_FIRST","overlapping_positions":False}
 @staticmethod
 def data():return {"candles":"public.candles_4h BTCUSDT","futures":"public.btc_futures_metrics_4h BTCUSDT","funding":"public.funding_rates BTCUSDT backward-asof","onchain":"public.btc_onchain_daily_raw available_at=day+1 UTC day","timeframe":"4h"}
 async def create_package(self,run_id,spec,result,signal_name,parity_fixture):
  p=PromotionPackage(research_run_id=run_id,experiment_id=result.experiment_id,signal_name=signal_name,experiment_spec=spec,validated_metrics=result,feature_contract=self.feature(spec),execution_contract=self.execution(spec),data_contract=self.data(),code_version=os.getenv("K_REVISION") or os.getenv("GIT_SHA") or "unversioned-local",prompt_version="btc-research-constitution-v1.0")
  payload=p.model_dump(mode="json");payload["parity_fixture"]=parity_fixture;h=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest();await self.db.insert("btc_research_promotion_packages",{"run_id":run_id,"experiment_id":result.experiment_id,"signal_name":signal_name,"status":"PENDING_PARITY","contract_hash":h,"package":payload})
  try:await self.db.insert("research_registry",{"key":f"external_btc_research_{result.experiment_id.lower()}","kind":"external_research_promotion_candidate","status":"pending_parity_no_production_authority","owner":"btc-research-engine","reason":f"Promotion package {h}; parity and shadow review required before APEX adoption."})
  except Exception:pass
  return p
