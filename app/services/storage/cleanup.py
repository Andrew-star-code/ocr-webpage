from app.core.metrics import CLEANUP_ERRORS, CLEANUP_FILES
from app.core.redis_lock import RedisLock
from app.services.jobs.state_machine import TERMINAL


class StorageCleanup:
    def __init__(self, redis, storage, lock_ttl):
        self.redis = redis
        self.storage = storage
        self.lock_ttl = lock_ttl

    async def run_once(self):
        lock = RedisLock(self.redis, "ocr:cleanup:lock", self.lock_ttl)
        if not await lock.acquire():
            return 0
        try:
            active = set()
            async for key in self.redis.scan_iter(match="ocr:job:*"):
                raw = await self.redis.get(key)
                if not raw:
                    continue
                import json

                try:
                    job = json.loads(raw)
                except ValueError:
                    continue
                if job.get("status") not in TERMINAL:
                    active.update(
                        identifier
                        for identifier in (job.get("input_file"), job.get("result_file"))
                        if identifier
                    )
            removed = await self.storage.cleanup_expired(active)
            if removed:
                CLEANUP_FILES.labels("expired").inc(removed)
            # Redis owns job metadata lifetime. Missing files must not erase failed/cancelled errors.
            return removed
        except Exception:
            CLEANUP_ERRORS.inc()
            raise
        finally:
            await lock.release()
