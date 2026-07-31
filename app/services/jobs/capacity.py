import time

_RESERVE = """
if redis.call('ZSCORE', KEYS[1], ARGV[1]) then return 1 end
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then return 0 end
redis.call('ZADD', KEYS[1], ARGV[3], ARGV[1])
return 1
"""
_RECONCILE = """
local reservations = redis.call('ZRANGE', KEYS[1], 0, -1, 'WITHSCORES')
local removed = 0
for index = 1, #reservations, 2 do
  local job_id = reservations[index]
  local reserved_at = tonumber(reservations[index + 1])
  local raw = redis.call('GET', ARGV[3] .. job_id)
  local remove = false
  if not raw then
    remove = true
  else
    local ok, job = pcall(cjson.decode, raw)
    if not ok then
      remove = true
    else
      local status = job['status']
      local terminal = status == 'completed' or status == 'completed_with_warnings'
        or status == 'failed' or status == 'cancelled'
      local stale = tonumber(ARGV[1]) - reserved_at > tonumber(ARGV[2])
      local lock_alive = redis.call('EXISTS', ARGV[4] .. job_id) == 1
      remove = terminal or (stale and not lock_alive)
    end
  end
  if remove then
    removed = removed + redis.call('ZREM', KEYS[1], job_id)
  end
end
return removed
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
        return int(
            await self.redis.eval(
                _RECONCILE,
                1,
                self.key,
                time.time(),
                self.processing_timeout,
                "ocr:job:",
                "ocr:worker-lock:",
            )
        )
