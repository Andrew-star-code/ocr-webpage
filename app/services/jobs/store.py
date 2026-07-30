import json
from datetime import datetime,timezone
from redis.asyncio import Redis
class JobStore:
 def __init__(self,url,ttl,redis=None):self.redis=redis or Redis.from_url(url,decode_responses=True);self.ttl=ttl;self._owned=redis is None
 async def create(self,j,options,input_file):
  now=datetime.now(timezone.utc).isoformat();value={"job_id":j,"status":"queued","stage":"queued","current_page":0,"total_pages":None,"progress":0.0,"retry_count":0,"created_at":now,"updated_at":now,"options":options,"input_file":input_file,"result_file":None};await self.redis.set(f"ocr:job:{j}",json.dumps(value),ex=self.ttl);return value
 async def get(self,j):
  value=await self.redis.get(f"ocr:job:{j}");return json.loads(value) if value else None
 async def update(self,j,**changes):
  value=await self.get(j)
  if not value:return None
  value.update(changes,updated_at=datetime.now(timezone.utc).isoformat());await self.redis.set(f"ocr:job:{j}",json.dumps(value),ex=self.ttl);return value
 async def delete(self,j):return bool(await self.redis.delete(f"ocr:job:{j}"))
 async def close(self):
  if self._owned:await self.redis.aclose()
