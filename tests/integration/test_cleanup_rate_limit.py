import asyncio
import os
import time
from types import SimpleNamespace

import pytest
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.rate_limit import RedisRateLimiter
from app.services.storage.cleanup import StorageCleanup
from app.services.storage.local import LocalDocumentStorage

URL = os.getenv("REDIS_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="REDIS_TEST_URL requires a real Redis")


@pytest.fixture
async def redis():
    client = Redis.from_url(URL, decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


def request(key, path="/v1/ocr", ip="127.0.0.1"):
    return SimpleNamespace(
        headers={"X-API-Key": key},
        url=SimpleNamespace(path=path),
        client=SimpleNamespace(host=ip),
        state=SimpleNamespace(request_id="r"),
    )


@pytest.mark.asyncio
async def test_rate_limit_hashes_valid_key_and_groups_random_invalid_keys(redis):
    settings = Settings(
        api_keys=["secret"], rate_limit_per_minute=1, rate_limit_unauthenticated_per_minute=1
    )
    a = RedisRateLimiter(settings, redis)
    assert await a.check(request("secret")) is None
    limited = await a.check(request("secret"))
    assert limited.status_code == 429 and "Retry-After" in limited.headers
    await redis.flushdb()
    assert await a.check(request("random-a")) is None
    assert (await a.check(request("random-b"))).status_code == 429
    keys = [key async for key in redis.scan_iter(match="ocr:rate:*")]
    assert keys and all("secret" not in key and "random" not in key for key in keys)


@pytest.mark.asyncio
async def test_cleanup_skips_active_and_fresh_and_removes_expired_orphans(redis, tmp_path):
    storage = LocalDocumentStorage(tmp_path / "in", tmp_path / "out", 1, 1)
    expired = await storage.save_input("old", b"x", "x")
    active = await storage.save_input("active", b"y", "x")
    fresh = await storage.save_result("fresh", b"z", "x", "json")
    for item in (expired, active):
        os.utime(storage._path(item.identifier), (time.time() - 5, time.time() - 5))
    await redis.set(
        "ocr:job:active",
        __import__("json").dumps(
            {"status": "recognizing", "input_file": active.identifier, "result_file": None}
        ),
    )
    orphan = storage.temp_dir / "orphan.dead.ref"
    orphan.write_text("input-missing.bin")
    os.utime(orphan, (time.time() - 5, time.time() - 5))
    removed = await StorageCleanup(redis, storage, 30).run_once()
    assert removed >= 2
    assert not await storage.exists(expired.identifier)
    assert await storage.exists(active.identifier)
    assert await storage.exists(fresh.identifier)
    assert not orphan.exists()


@pytest.mark.asyncio
async def test_cleanup_distributed_lock_allows_one_owner(redis, tmp_path):
    storage = LocalDocumentStorage(tmp_path / "in", tmp_path / "out", 1, 1)
    item = await storage.save_input("old", b"x", "x")
    os.utime(storage._path(item.identifier), (time.time() - 5, time.time() - 5))
    cleaner = StorageCleanup(redis, storage, 30)
    results = await asyncio.gather(cleaner.run_once(), cleaner.run_once())
    assert sum(results) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "cancelled", "completed"])
async def test_cleanup_preserves_terminal_metadata_until_redis_ttl(redis, tmp_path, status):
    import json

    storage = LocalDocumentStorage(tmp_path / "in", tmp_path / "out", 1, 1)
    await redis.set(
        f"ocr:job:{status}",
        json.dumps({"status": status, "input_file": "input-missing.bin", "result_file": None}),
        ex=60,
    )
    await StorageCleanup(redis, storage, 30).run_once()
    assert await redis.exists(f"ocr:job:{status}")
    assert await redis.ttl(f"ocr:job:{status}") > 0


@pytest.mark.asyncio
async def test_cleanup_atomic_temp_grace_period(redis, tmp_path):
    storage = LocalDocumentStorage(tmp_path / "in", tmp_path / "out", 1, 1)
    temporary = storage.temp_dir / ".input-dead.bin.abc.tmp"
    temporary.write_bytes(b"partial")
    await StorageCleanup(redis, storage, 30).run_once()
    assert temporary.exists()
    os.utime(temporary, (time.time() - 120, time.time() - 120))
    await StorageCleanup(redis, storage, 30).run_once()
    assert not temporary.exists()


class BrokenRedis:
    async def eval(self, *args):
        from redis.exceptions import ConnectionError

        raise ConnectionError("offline")


@pytest.mark.asyncio
async def test_rate_limit_redis_failure_policy_and_operational_bypass():
    settings = Settings(api_keys=["secret"])
    limiter = RedisRateLimiter(settings, BrokenRedis())
    response = await limiter.check(request("secret", "/v1/ocr"))
    assert response.status_code == 503
    assert b"dependency_unavailable" in response.body
    assert await limiter.check(request("", "/health")) is None
    assert await limiter.check(request("", "/ready")) is None
    assert await limiter.check(request("", "/metrics")) is None
