import asyncio
import os

import pytest
from redis.asyncio import Redis

from app.core.redis_lock import RedisLock

URL = os.getenv("REDIS_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="REDIS_TEST_URL requires a real Redis")


@pytest.fixture
async def redis():
    client = Redis.from_url(URL, decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.mark.asyncio
async def test_lock_release_and_extend_require_ownership(redis):
    owner = RedisLock(redis, "lock", 2, "owner")
    stranger = RedisLock(redis, "lock", 2, "stranger")
    assert await owner.acquire()
    assert not await stranger.extend()
    assert not await stranger.release()
    assert await owner.extend()
    assert await owner.release()


@pytest.mark.asyncio
async def test_expired_lock_cannot_be_deleted_by_old_owner(redis):
    old = RedisLock(redis, "lock", 1, "old")
    assert await old.acquire()
    await asyncio.sleep(1.1)
    new = RedisLock(redis, "lock", 5, "new")
    assert await new.acquire()
    assert not await old.release()
    assert await redis.get("lock") == "new"


@pytest.mark.asyncio
async def test_lock_renewal_and_ownership_loss(redis):
    owner = RedisLock(redis, "lock", 2, "owner")
    assert await owner.acquire()
    stop = asyncio.Event()
    lost = asyncio.Event()
    task = asyncio.create_task(owner.renew_until_stopped(stop, lost, 1))
    await asyncio.sleep(1.2)
    assert await redis.ttl("lock") > 0 and not lost.is_set()
    await redis.set("lock", "other", ex=2)
    await asyncio.sleep(1.1)
    assert lost.is_set()
    stop.set()
    await task


class FailingExtendRedis:
    async def set(self, *args, **kwargs):
        return True

    async def eval(self, *args, **kwargs):
        raise ConnectionError("redis lost")


@pytest.mark.asyncio
async def test_renewal_exception_marks_ownership_lost_fail_closed():
    lock = RedisLock(FailingExtendRedis(), "lock", 2, "owner")
    stop = asyncio.Event()
    lost = asyncio.Event()
    await lock.renew_until_stopped(stop, lost, 0.01)
    assert lost.is_set()
