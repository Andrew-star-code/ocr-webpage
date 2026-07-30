import json
from datetime import datetime,timezone
from redis.asyncio import Redis
class JobStore:
 def __init__(self,url,ttl): self.redis=Redis.from_url(url,decode_responses=True); self.ttl=ttl
 async def create(self,j,o):
  n=datetime.now(timezone.utc).isoformat(); v={"job_id":j,"status":"queued","stage":"queued","current_page":0,"total_pages":None,"progress":0,"retry_count":0,"created_at":n,"updated_at":n,"options":o}; await self.redis.set(f"ocr:job:{j}",json.dumps(v),ex=self.ttl); return v
 async def get(self,j):
  v=await self.redis.get(f"ocr:job:{j}"); return json.loads(v) if v else None
 async def update(self,j,**c):
  v=await self.get(j)
  if not v:return None
  v.update(c,updated_at=datetime.now(timezone.utc).isoformat()); await self.redis.set(f"ocr:job:{j}",json.dumps(v),ex=self.ttl); return v
 async def delete(self,j): return bool(await self.redis.delete(f"ocr:job:{j}",f"ocr:result:{j}",f"ocr:input:{j}"))
