from __future__ import annotations
import asyncio,os
from google.cloud import run_v2
async def launch_job(run_id:str)->str|None:
 project=os.getenv("GOOGLE_CLOUD_PROJECT"); region=os.getenv("CLOUD_RUN_REGION","us-central1"); job=os.getenv("CLOUD_RUN_RESEARCH_JOB")
 if not project or not job:return None
 name=f"projects/{project}/locations/{region}/jobs/{job}"
 def _run():
  client=run_v2.JobsClient(); req=run_v2.RunJobRequest(name=name,overrides=run_v2.RunJobRequest.Overrides(container_overrides=[run_v2.RunJobRequest.Overrides.ContainerOverride(env=[run_v2.EnvVar(name="RESEARCH_RUN_ID",value=run_id)])])); op=client.run_job(request=req); return op.operation.name if getattr(op,"operation",None) else str(op)
 return await asyncio.to_thread(_run)
