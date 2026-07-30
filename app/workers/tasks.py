import asyncio,dramatiq
from dramatiq.brokers.redis import RedisBroker
from redis.asyncio import Redis
from app.core.config import get_settings
from app.services.exporters.all import EXPORTERS
from app.services.jobs.store import JobStore
from app.services.recognition.pipeline import RecognitionPipeline
from app.services.vision.registry import create_backend
s=get_settings();dramatiq.set_broker(RedisBroker(url=s.redis_url))
@dramatiq.actor(max_retries=0)
def recognize_job(job_id): asyncio.run(run(job_id))
async def run(j):
 store=JobStore(s.redis_url,s.result_ttl_seconds);redis=Redis.from_url(s.redis_url);job=await store.get(j)
 if not job or job["status"]=="cancelled":return
 backend=create_backend(s);await store.update(j,status="recognizing",stage="vision_inference")
 try:
  o=job["options"];doc=await RecognitionPipeline(s,backend).run(await redis.get(f"ocr:input:{j}"),o["language"],o["model_profile"],o["preprocess_mode"],o["normalize_text"],o["detect_tables"],o["dpi"],o["allow_partial_result"])
  if (await store.get(j))["status"]=="cancelled":return
  await redis.set(f"ocr:result:{j}",EXPORTERS[o["output_format"]](doc),ex=s.result_ttl_seconds);await store.update(j,status="completed_with_warnings" if doc.partial else "completed",stage="completed",current_page=len(doc.pages),total_pages=len(doc.pages),progress=100,retry_count=doc.metadata.retries)
 except Exception: await store.update(j,status="failed",stage="failed",error={"code":"vision_inference_failed","message":"Document processing failed"})
 finally: await backend.client.aclose()
