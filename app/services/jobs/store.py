import json
from datetime import datetime,timezone
from redis.asyncio import Redis
from app.services.jobs.state_machine import JobStateConflict,validate_transition
_UPDATE_LUA='''
local raw=redis.call('GET',KEYS[1]); if not raw then return {0,''} end
local state=cjson.decode(raw)
if state.status~=ARGV[1] or tonumber(state.version)~=tonumber(ARGV[2]) then return {-1,raw} end
local patch=cjson.decode(ARGV[3]); for k,v in pairs(patch) do state[k]=v end
state.version=state.version+1; state.updated_at=ARGV[4]
local encoded=cjson.encode(state); redis.call('SET',KEYS[1],encoded,'EX',ARGV[5]); return {1,encoded}
'''
class JobStore:
 def __init__(self,url,ttl,redis=None):self.redis=redis or Redis.from_url(url,decode_responses=True);self.ttl=ttl;self._owned=redis is None
 async def create(self,j,options,input_file):
  now=datetime.now(timezone.utc).isoformat();value={"job_id":j,"status":"queued","stage":"queued","current_page":0,"total_pages":None,"progress":0.0,"retry_count":0,"version":1,"created_at":now,"updated_at":now,"options":options,"input_file":input_file,"result_file":None};created=await self.redis.set(f"ocr:job:{j}",json.dumps(value),ex=self.ttl,nx=True)
  if not created:raise JobStateConflict("Job already exists")
  return value
 async def get(self,j):
  value=await self.redis.get(f"ocr:job:{j}");return json.loads(value) if value else None
 async def update(self,j,expected_status=None,expected_version=None,**changes):
  current=await self.get(j)
  if not current:return None
  target=changes.get("status",current["status"]);validate_transition(current["status"],target)
  expected_status=expected_status or current["status"];expected_version=expected_version or current["version"]
  now=datetime.now(timezone.utc).isoformat();result=await self.redis.eval(_UPDATE_LUA,1,f"ocr:job:{j}",expected_status,expected_version,json.dumps(changes),now,self.ttl)
  code=int(result[0])
  if code==-1:raise JobStateConflict()
  return json.loads(result[1]) if code==1 else None
 async def transition(self,j,target,expected_status=None,**changes):return await self.update(j,expected_status=expected_status,status=target,**changes)
 async def delete(self,j):return bool(await self.redis.delete(f"ocr:job:{j}"))
 async def close(self):
  if self._owned:await self.redis.aclose()
