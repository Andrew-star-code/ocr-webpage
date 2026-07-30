import asyncio,json,threading,time
import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import Middleware
from redis import Redis as SyncRedis
from redis.asyncio import Redis
from app.core.config import get_settings
from app.core.exceptions import ServiceError
from app.services.exporters.base import ExportOptions
from app.services.exporters.registry import ExporterRegistry
from app.services.jobs.store import JobStore
from app.services.recognition.pipeline import RecognitionPipeline
from app.services.storage.local import LocalDocumentStorage
from app.services.vision.profiles import ProfileRegistry
from app.services.vision.registry import create_backends
s=get_settings()
def _heartbeat():
 redis=SyncRedis.from_url(s.redis_url)
 while True:
  try:redis.set("ocr:worker:heartbeat",str(time.time()),ex=s.worker_heartbeat_ttl*2)
  except Exception:time.sleep(2)
  time.sleep(max(2,s.worker_heartbeat_ttl//3))
class HeartbeatMiddleware(Middleware):
 def after_worker_boot(self,broker,worker):threading.Thread(target=_heartbeat,daemon=True,name="ocr-heartbeat").start()
broker=RedisBroker(url=s.redis_url);broker.add_middleware(HeartbeatMiddleware());dramatiq.set_broker(broker)
@dramatiq.actor(max_retries=0,time_limit=s.document_processing_timeout*1000)
def recognize_job(job_id):asyncio.run(run(job_id))
async def run(job_id):
 redis=Redis.from_url(s.redis_url,decode_responses=True);store=JobStore(s.redis_url,s.result_ttl_seconds,redis);storage=LocalDocumentStorage(s.temp_dir,s.result_dir,s.temp_file_ttl_seconds,s.result_ttl_seconds);backends=create_backends(s);profiles=ProfileRegistry.load(s.profile_dir);pipeline=RecognitionPipeline(s,backends,profiles)
 async def cancelled():
  current=await store.get(job_id);return not current or current["status"]=="cancelled"
 async def progress(stage,current,total,retries):await store.update(job_id,status="recognizing",stage=stage,current_page=current,total_pages=total,progress=round(current/total*100,1) if total else 0,retry_count=retries)
 try:
  job=await store.get(job_id)
  if not job or await cancelled():return
  await store.update(job_id,status="validating",stage="storage_read");data=await storage.read_input(job["input_file"]);o=job["options"]
  result=await pipeline.run(data,o["language"],o["model_profile"],o["preprocess_mode"],o["normalize_text"],o["detect_tables"],o["dpi"],o["allow_partial_result"],progress,cancelled)
  if await cancelled():return
  await store.update(job_id,status="exporting",stage="exporting");exporter=ExporterRegistry().get(o["output_format"]);body=exporter.export(result,ExportOptions(o["preserve_layout"],o["include_bounding_boxes"],o["include_processing_metadata"]));stored=await storage.save_result(job_id,body,exporter.mime_type,exporter.extension);await storage.tag_job_file(job_id,stored)
  await store.update(job_id,status="completed_with_warnings" if result.document.partial or result.document.warnings else "completed",stage="completed",current_page=len(result.document.pages),total_pages=len(result.document.pages),progress=100,result_file=stored.identifier)
 except ServiceError as exc:await store.update(job_id,status="cancelled" if exc.code=="processing_cancelled" else "failed",stage="failed",error={"code":exc.code,"message":exc.message,"details":exc.details})
 except Exception:await store.update(job_id,status="failed",stage="failed",error={"code":"internal_error","message":"Internal processing error"})
 finally:
  job=await store.get(job_id)
  if job and job.get("input_file"):await storage.delete_file(job["input_file"])
  await redis.decr("ocr:queue:size");await backends.close();await redis.aclose()
