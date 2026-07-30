import json,time,uuid
from app.core.metrics import CLEANUP_ERRORS,CLEANUP_FILES
from app.services.jobs.state_machine import TERMINAL
class StorageCleanup:
 def __init__(self,redis,storage,lock_ttl):self.redis=redis;self.storage=storage;self.lock_ttl=lock_ttl
 async def run_once(self):
  token=uuid.uuid4().hex;lock="ocr:cleanup:lock"
  if not await self.redis.set(lock,token,nx=True,ex=self.lock_ttl):return 0
  try:
   active=set();jobs=[]
   async for key in self.redis.scan_iter(match="ocr:job:*"):
    raw=await self.redis.get(key)
    try:job=json.loads(raw);jobs.append((key,job))
    except (TypeError,ValueError):await self.redis.delete(key);continue
    if job.get("status") not in TERMINAL:active.update(x for x in (job.get("input_file"),job.get("result_file")) if x)
   removed=await self.storage.cleanup_expired(active)
   if removed:CLEANUP_FILES.labels("expired").inc(removed)
   for key,job in jobs:
    identifier=job.get("result_file") if job.get("status") in {"completed","completed_with_warnings"} else job.get("input_file")
    if identifier and not await self.storage.exists(identifier) and job.get("status") in TERMINAL:
     await self.redis.delete(key);CLEANUP_FILES.labels("metadata").inc();removed+=1
   return removed
  except Exception:
   CLEANUP_ERRORS.inc();raise
  finally:
   if await self.redis.get(lock)==token:await self.redis.delete(lock)
