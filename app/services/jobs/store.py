import json
from datetime import datetime, timezone

from redis.asyncio import Redis

from app.services.jobs.state_machine import TERMINAL, JobStateConflict, validate_transition

_UPDATE_LUA = """
local raw=redis.call('GET',KEYS[1]); if not raw then return {0,''} end
local state=cjson.decode(raw)
if state.status~=ARGV[1] or tonumber(state.version)~=tonumber(ARGV[2]) then return {-1,raw} end
local patch=cjson.decode(ARGV[3]); for k,v in pairs(patch) do state[k]=v end
state.version=state.version+1; state.updated_at=ARGV[4]
local encoded=cjson.encode(state); redis.call('SET',KEYS[1],encoded,'EX',ARGV[5]); return {1,encoded}
"""
ACTIVE = {"validating", "rendering", "preprocessing", "recognizing", "assembling", "exporting"}


class JobStore:
    def __init__(self, url, ttl, redis=None):
        self.redis = redis or Redis.from_url(url, decode_responses=True)
        self.ttl = ttl
        self._owned = redis is None

    async def create(self, job_id, options, input_file):
        now = datetime.now(timezone.utc).isoformat()
        value = {
            "job_id": job_id,
            "status": "queued",
            "stage": "queued",
            "current_page": 0,
            "total_pages": None,
            "progress": 0.0,
            "retry_count": 0,
            "version": 1,
            "created_at": now,
            "updated_at": now,
            "options": options,
            "input_file": input_file,
            "result_file": None,
        }
        created = await self.redis.set(f"ocr:job:{job_id}", json.dumps(value), ex=self.ttl, nx=True)
        if not created:
            raise JobStateConflict("Job already exists")
        return value

    async def get(self, job_id):
        value = await self.redis.get(f"ocr:job:{job_id}")
        return json.loads(value) if value else None

    async def update(self, job_id, expected_status=None, expected_version=None, **changes):
        current = await self.get(job_id)
        if not current:
            return None
        target = changes.get("status", current["status"])
        validate_transition(current["status"], target)
        expected_status = expected_status or current["status"]
        expected_version = expected_version or current["version"]
        now = datetime.now(timezone.utc).isoformat()
        result = await self.redis.eval(
            _UPDATE_LUA,
            1,
            f"ocr:job:{job_id}",
            expected_status,
            expected_version,
            json.dumps(changes),
            now,
            self.ttl,
        )
        code = int(result[0])
        if code == -1:
            raise JobStateConflict()
        return json.loads(result[1]) if code == 1 else None

    async def transition(self, job_id, target, expected_status=None, **changes):
        return await self.update(job_id, expected_status=expected_status, status=target, **changes)

    async def update_progress(self, job_id, target, retries=3, **changes):
        for _ in range(retries):
            current = await self.get(job_id)
            if not current or current["status"] in TERMINAL:
                return current
            if current["status"] not in ACTIVE and current["status"] != "queued":
                return current
            try:
                return await self.update(
                    job_id,
                    expected_status=current["status"],
                    expected_version=current["version"],
                    status=target,
                    **changes,
                )
            except JobStateConflict:
                latest = await self.get(job_id)
                if not latest or latest["status"] in TERMINAL:
                    return latest
        raise JobStateConflict("Progress update exceeded retry limit")

    async def cancel(self, job_id):
        while True:
            current = await self.get(job_id)
            if not current or current["status"] == "cancelled":
                return current
            if current["status"] in TERMINAL:
                return current
            try:
                return await self.update(
                    job_id,
                    expected_status=current["status"],
                    expected_version=current["version"],
                    status="cancelled",
                    stage="cancelled",
                )
            except JobStateConflict:
                continue

    async def complete(self, job_id, target="completed", **changes):
        current = await self.get(job_id)
        if not current or current["status"] in TERMINAL:
            return current
        return await self.update(
            job_id,
            expected_status="exporting",
            expected_version=current["version"],
            status=target,
            stage="completed",
            **changes,
        )

    async def fail(self, job_id, error):
        current = await self.get(job_id)
        if not current or current["status"] in TERMINAL:
            return current
        try:
            return await self.update(
                job_id,
                expected_status=current["status"],
                expected_version=current["version"],
                status="failed",
                stage="failed",
                error=error,
            )
        except JobStateConflict:
            return await self.get(job_id)

    async def delete(self, job_id):
        return bool(await self.redis.delete(f"ocr:job:{job_id}"))

    async def close(self):
        if self._owned:
            await self.redis.aclose()
