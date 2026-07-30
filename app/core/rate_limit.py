import hashlib
import secrets
import time

from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError, ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.core.config import Settings
from app.core.metrics import RATE_LIMIT_ERRORS

_LUA = """
local n=redis.call('INCR',KEYS[1])
if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end
return {n,redis.call('TTL',KEYS[1])}
"""


class RedisRateLimiter:
    def __init__(self, settings: Settings, redis=None):
        self.settings = settings
        self.redis = redis or Redis.from_url(settings.redis_url, decode_responses=True)
        self.owned = redis is None

    def _identity(self, request):
        supplied = request.headers.get("X-API-Key", "")
        valid = next(
            (key for key in self.settings.api_keys if secrets.compare_digest(supplied, key)),
            None,
        )
        if valid:
            return (
                "key:" + hashlib.sha256(valid.encode()).hexdigest(),
                self.settings.rate_limit_per_minute,
            )
        ip = request.client.host if request.client else "unknown"
        return (
            "ip:" + hashlib.sha256(ip.encode()).hexdigest(),
            self.settings.rate_limit_unauthenticated_per_minute,
        )

    async def check(self, request):
        if request.url.path in {"/health", "/ready", "/metrics"}:
            return None
        identity, limit = self._identity(request)
        bucket = int(time.time() // 60)
        try:
            count, ttl = await self.redis.eval(_LUA, 1, f"ocr:rate:{identity}:{bucket}", 60)
        except (RedisTimeoutError, RedisConnectionError, ResponseError, RedisError):
            RATE_LIMIT_ERRORS.inc()
            return JSONResponse(
                {
                    "error": {
                        "code": "dependency_unavailable",
                        "message": "Rate limit storage is unavailable",
                        "details": {"dependency": "redis"},
                        "request_id": request.state.request_id,
                    }
                },
                503,
            )
        if int(count) > limit:
            retry = max(1, int(ttl))
            return JSONResponse(
                {
                    "error": {
                        "code": "rate_limited",
                        "message": "Rate limit exceeded",
                        "details": {},
                        "request_id": request.state.request_id,
                    }
                },
                429,
                headers={"Retry-After": str(retry)},
            )
        return None

    async def close(self):
        if self.owned:
            await self.redis.aclose()
