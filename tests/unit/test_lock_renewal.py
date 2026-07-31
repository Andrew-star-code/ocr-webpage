import asyncio

from app.core.redis_lock import RedisLock


class RedisFailure:
    async def eval(self, *args):
        raise TimeoutError("redis timeout")


class RedisLostOwnership:
    async def eval(self, *args):
        return 0


def _renew(redis):
    async def scenario():
        stop = asyncio.Event()
        ownership_lost = asyncio.Event()
        lock = RedisLock(redis, "lock", 10, "owner")
        await lock.renew_until_stopped(stop, ownership_lost, 0.001)
        return ownership_lost.is_set()

    return asyncio.run(scenario())


def test_renewal_timeout_fails_closed():
    assert _renew(RedisFailure())


def test_failed_extension_fails_closed():
    assert _renew(RedisLostOwnership())
