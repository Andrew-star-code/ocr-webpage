import asyncio,threading,time,uuid
import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import Middleware
from redis import Redis as SyncRedis
from redis.asyncio import Redis
from app.core.config import get_settings
from app.core.exceptions import ServiceError
from app.services.exporters.base import ExportOptions
from app.services.exporters.registry import ExporterRegistry
from app.services.jobs.capacity import QueueCapacity
from app.services.jobs.state_machine import JobStateConflict
from app.services.jobs.store import JobStore
from app.services.recognition.pipeline import ProcessingCancelled,RecognitionPipeline
from app.services.storage.local import LocalDocumentStorage
from app.services.storage.cleanup import StorageCleanup
from app.services.vision.profiles import ProfileRegistry
from app.services.vision.registry import create_backends
s=get_settings()
def _heartbeat():
 redis=SyncRedis.from_url(s.redis_url)
 while True:
  try:redis.set("ocr:worker:heartbeat",str(time.time()),ex=s.worker_heartbeat_ttl*2)
  except Exception:time.sleep(2)
  time.sleep(max(2,s.worker_heartbeat_ttl//3))
def _cleanup_loop():
 while True:
  async def clean():
   redis=Redis.from_url(s.redis_url,decode_responses=True);storage=LocalDocumentStorage(s.temp_dir,s.result_dir,s.temp_file_ttl_seconds,s.result_ttl_seconds)
   try:await StorageCleanup(redis,storage,s.cleanup_lock_ttl_seconds).run_once();await QueueCapacity(redis,s.max_queue_size).reconcile()
   finally:await redis.aclose()
  try:asyncio.run(clean())
  except Exception:time.sleep(5)
  time.sleep(s.cleanup_interval_seconds)
class HeartbeatMiddleware(Middleware):
 def after_worker_boot(self,broker,worker):
  threading.Thread(target=_heartbeat,daemon=True,name="ocr-heartbeat").start();threading.Thread(target=_cleanup_loop,daemon=True,name="ocr-cleanup").start()
broker=RedisBroker(url=s.redis_url);broker.add_middleware(HeartbeatMiddleware());dramatiq.set_broker(broker)
@dramatiq.actor(max_retries=0,time_limit=s.document_processing_timeout*1000)
def recognize_job(job_id):asyncio.run(run(job_id))
async def run(job_id):
 redis=Redis.from_url(s.redis_url,decode_responses=True);store=JobStore(s.redis_url,s.result_ttl_seconds,redis);capacity=QueueCapacity(redis,s.max_queue_size);storage=LocalDocumentStorage(s.temp_dir,s.result_dir,s.temp_file_ttl_seconds,s.result_ttl_seconds);backends=create_backends(s);profiles=ProfileRegistry.load(s.profile_dir);pipeline=RecognitionPipeline(s,backends,profiles);lock=f"ocr:worker-lock:{job_id}";token=uuid.uuid4().hex
 acquired=await redis.set(lock,token,nx=True,ex=s.document_processing_timeout)
 if not acquired:await backends.close();await redis.aclose();return
 async def cancelled():
  current=await store.get(job_id);return not current or current["status"]=="cancelled"
 async def ensure_active():
  if await cancelled():raise ProcessingCancelled()
 async def progress(stage,current,total,retries):
  await ensure_active();job=await store.get(job_id);target="rendering" if stage=="rendering" else "recognizing"
  try:await store.transition(job_id,target,expected_status=job["status"],stage=stage,current_page=current,total_pages=total,progress=round(current/total*100,1) if total else 0,retry_count=retries)
  except JobStateConflict:
   if await cancelled():raise ProcessingCancelled()
   raise
 try:
  job=await store.get(job_id)
  if not job or job["status"]!="queued":return
  await store.transition(job_id,"validating",expected_status="queued",stage="storage_read");await ensure_active();data=await storage.read_input(job["input_file"]);o=job["options"]
  result=await pipeline.run(data,o["language"],o["model_profile"],o["preprocess_mode"],o["normalize_text"],o["detect_tables"],o["dpi"],o["allow_partial_result"],progress,cancelled)
  await ensure_active();current=await store.get(job_id);await store.transition(job_id,"exporting",expected_status=current["status"],stage="exporting");exporter=ExporterRegistry().get(o["output_format"]);body=exporter.export(result,ExportOptions(o["preserve_layout"],o["include_bounding_boxes"],o["include_processing_metadata"]));await ensure_active()
  stored=await storage.save_result(job_id,body,exporter.mime_type,exporter.extension);await ensure_active();await storage.tag_job_file(job_id,stored);target="completed_with_warnings" if result.document.partial or result.document.warnings else "completed";await store.transition(job_id,target,expected_status="exporting",stage="completed",current_page=len(result.document.pages),total_pages=len(result.document.pages),progress=100,result_file=stored.identifier)
 except ProcessingCancelled:
  current=await store.get(job_id)
  if current and current["status"] not in {"cancelled","completed","completed_with_warnings","failed"}:
   try:await store.transition(job_id,"cancelled",stage="cancelled")
   except JobStateConflict:None
 except ServiceError as exc:
  current=await store.get(job_id)
  if current and current["status"]!="cancelled":
   try:await store.transition(job_id,"failed",stage="failed",error={"code":exc.code,"message":exc.message,"details":exc.details})
   except JobStateConflict:None
 except Exception:
  current=await store.get(job_id)
  if current and current["status"]!="cancelled":
   try:await store.transition(job_id,"failed",stage="failed",error={"code":"internal_error","message":"Internal processing error"})
   except JobStateConflict:None
 finally:
  job=await store.get(job_id)
  if job and job.get("input_file"):await storage.delete_file(job["input_file"])
  await capacity.release(job_id)
  if await redis.get(lock)==token:await redis.delete(lock)
  await backends.close();await redis.aclose()
