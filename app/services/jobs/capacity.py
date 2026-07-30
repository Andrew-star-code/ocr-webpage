import time
from redis.asyncio import Redis
_RESERVE='''
if redis.call('ZSCORE',KEYS[1],ARGV[1]) then return 1 end
if redis.call('ZCARD',KEYS[1])>=tonumber(ARGV[2]) then return 0 end
redis.call('ZADD',KEYS[1],ARGV[3],ARGV[1]); return 1
'''
class QueueCapacity:
 def __init__(self,redis:Redis,limit:int,key="ocr:queue:jobs"):self.redis=redis;self.limit=limit;self.key=key
 async def reserve(self,job_id):return bool(await self.redis.eval(_RESERVE,1,self.key,job_id,self.limit,time.time()))
 async def release(self,job_id):return bool(await self.redis.zrem(self.key,job_id))
 async def size(self):return int(await self.redis.zcard(self.key))
 async def reconcile(self):
  members=await self.redis.zrange(self.key,0,-1);removed=0
  for job_id in members:
   if not await self.redis.exists(f"ocr:job:{job_id}"):removed+=await self.redis.zrem(self.key,job_id)
  return int(removed)
