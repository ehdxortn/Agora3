from __future__ import annotations
import hashlib,json,os
from .models import PromotionPackage
from .parity import verify_parity
class PromotionManager:
 def __init__(self,db):self.db=db
 @staticmethod
 def feature(spec):return {"decision_clock":"completed BTC 4H candle close","entry_clock":"next BTC 4H candle open","features":[f.model_dump() for f in spec.features],"conditions":[c.model_dump() for c in spec.conditions],"no_future_data":True,"onchain_lag":"2 completed UTC days by default","threshold_training":"train split only for train_quantile thresholds"}
 @staticmethod
 def execution(spec):return {"side":spec.side,"entry":"next_candle_open","exit":spec.exit.model_dump(),"fee_bps":spec.fee_bps,"slippage_bps":spec.slippage_bps,"same_bar_stop_target_rule":"STOP_FIRST","overlapping_positions":False}
 async def create_package(self,run_id,spec,result,signal_name,fixture):
  if not result.holdout_revealed or not result.passed_minimum_gate:raise ValueError("Promotion requires a revealed passing sealed holdout")
  data={"candles":"public.candles_4h symbol=BTC","futures":"public.btc_futures_metrics_4h symbol=BTCUSDT; incomplete slots excluded","funding":"public.funding_rates symbol=BTC backward-asof","onchain":"public.btc_onchain_daily_raw lagged conservatively","timeframe":"4h","fingerprint":fixture["dataset_fingerprint"]}
  p=PromotionPackage(research_run_id=run_id,experiment_id=result.experiment_id,signal_name=signal_name,experiment_spec=spec,validated_metrics=result,feature_contract=self.feature(spec),execution_contract=self.execution(spec),data_contract=data,resolved_thresholds=fixture["resolved_thresholds"],parity_fixture=fixture,code_version=os.getenv("GIT_SHA") or os.getenv("K_REVISION") or "unversioned-local",prompt_version="btc-research-constitution-v1.0")
  payload=p.model_dump(mode="json");h=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest();await self.db.insert("btc_research_promotion_packages",{"run_id":run_id,"experiment_id":result.experiment_id,"signal_name":signal_name,"status":"PENDING_PARITY","contract_hash":h,"package":payload})
  try:await self.db.insert("research_registry",{"key":f"external_btc_research_{result.experiment_id.lower()}","kind":"external_research_promotion_candidate","status":"pending_parity_no_production_authority","owner":"btc-research-engine","reason":f"Promotion package {h}; 100% parity and shadow review required before APEX adoption."})
  except Exception:pass
  return p
 async def verify_and_mark(self,run_id,experiment_id,vectors,tolerance):
  rows=await self.db.select("btc_research_promotion_packages","*",limit=1,run_id=run_id,experiment_id=experiment_id)
  if not rows:raise LookupError("promotion package not found")
  row=rows[0];result=verify_parity(row["package"]["parity_fixture"],vectors,tolerance)
  await self.db.add_event(run_id,"PARITY_CHECK",{"experiment_id":experiment_id,**result})
  if result["passed"]:
   package=dict(row["package"]);package["status"]="PARITY_PASSED";await self.db.update("btc_research_promotion_packages",{"status":"PARITY_PASSED","package":package},id=row["id"])
   try:await self.db.update("research_registry",{"status":"parity_passed_shadow_only","reason":f"Parity passed for {row['contract_hash']}; still no production authority."},key=f"external_btc_research_{experiment_id.lower()}")
   except Exception:pass
  return result
