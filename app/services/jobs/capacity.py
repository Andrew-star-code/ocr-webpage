import json
import time

from app.services.jobs.state_machine import TERMINAL

_RESERVE = """
if redis.call('ZSCORE', KEYS[1], ARGV[1]) then return 1 end
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then return 0 end
redis.call('ZADD', KEYS[1], ARGV[3], ARGV[1])
return 1
"""
_REMOVE_IF_SCORE = """
local current = redis.call('ZSCORE', KEYS[1], ARGV[1])
if current and tonumber(current) == tonumber(ARGV[2]) then
  return redis.call('ZREM', KEYS[1], ARGV[1])
end
return 0
"""


class QueueCapacity:
    def __init__(self, redis, limit: int, processing_timeout: int = 7200, key="ocr:queue:jobs"):
        self.redis = redis
        self.limit = limit
        self.processing_timeout = processing_timeout
        self.key = key

    async def reserve(self, job_id: str) -> bool:
        return bool(await self.redis.eval(_RESERVE, 1, self.key, job_id, self.limit, time.time()))

    async def release(self, job_id: str) -> bool:
        return bool(await self.redis.zrem(self.key, job_id))

    async def size(self) -> int:
        return int(await self.redis.zcard(self.key))

    async def reconcile(self) -> int:
        now = time.time()
        removed = 0
        reservations = await self.redis.zrange(self.key, 0, -1, withscores=True)
        for job_id, reserved_at in reservations:
            raw = await self.redis.get(f"ocr:job:{job_id}")
            job = json.loads(raw) if raw else None
            terminal = bool(job and job.get("status") in TERMINAL)
            stale = now - float(reserved_at) > self.processing_timeout
            lock_alive = bool(await self.redis.exists(f"ocr:worker-lock:{job_id}"))
            if job is None or terminal or (stale and not lock_alive):
                removed += int(
                    await self.redis.eval(_REMOVE_IF_SCORE, 1, self.key, job_id, reserved_at)
                )
        return removed
