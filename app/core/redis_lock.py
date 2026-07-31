import asyncio
import uuid

_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""
_EXTEND = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""


class RedisLock:
    def __init__(self, redis, key: str, ttl_seconds: int, token: str | None = None):
        self.redis = redis
        self.key = key
        self.ttl_seconds = ttl_seconds
        self.token = token or uuid.uuid4().hex

    async def acquire(self) -> bool:
        return bool(await self.redis.set(self.key, self.token, nx=True, ex=self.ttl_seconds))

    async def extend(self) -> bool:
        return bool(await self.redis.eval(_EXTEND, 1, self.key, self.token, self.ttl_seconds))

    async def release(self) -> bool:
        return bool(await self.redis.eval(_RELEASE, 1, self.key, self.token))

    async def renew_until_stopped(
        self, stop: asyncio.Event, ownership_lost: asyncio.Event, interval: int
    ):
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except TimeoutError:
                if not await self.extend():
                    ownership_lost.set()
                    return
