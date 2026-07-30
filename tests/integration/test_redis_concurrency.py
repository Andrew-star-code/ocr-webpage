import asyncio,os
import pytest
from redis.asyncio import Redis
from app.services.jobs.capacity import QueueCapacity
from app.services.jobs.state_machine import JobStateConflict
from app.services.jobs.store import JobStore
URL=os.getenv("REDIS_TEST_URL")
pytestmark=pytest.mark.skipif(not URL,reason="REDIS_TEST_URL requires a real Redis")
@pytest.fixture
async def redis():
 client=Redis.from_url(URL,decode_responses=True);await client.flushdb();yield client;await client.flushdb();await client.aclose()
@pytest.mark.asyncio
async def test_capacity_concurrent_reserve_is_bounded_and_idempotent(redis):
 capacity=QueueCapacity(redis,3);values=await asyncio.gather(*(capacity.reserve(f"j{i}") for i in range(12)));assert sum(values)==3 and await capacity.size()==3;assert await capacity.reserve("j0") and await capacity.size()==3;assert await capacity.release("j0") and not await capacity.release("j0")
@pytest.mark.asyncio
async def test_cancel_wins_over_stale_progress(redis):
 store=JobStore(URL,300,redis);job=await store.create("j",{},"input");valid=await store.transition("j","validating",expected_status="queued");cancelled=await store.transition("j","cancelled",expected_status="validating")
 with pytest.raises(JobStateConflict):await store.update("j",expected_status="validating",expected_version=valid["version"],progress=50,status="recognizing")
 assert (await store.get("j"))["status"]=="cancelled" and cancelled["version"]==3
@pytest.mark.asyncio
async def test_terminal_and_duplicate_delivery_are_rejected(redis):
 store=JobStore(URL,300,redis);await store.create("j",{},"input");await store.transition("j","validating");await store.transition("j","rendering");await store.transition("j","recognizing");await store.transition("j","exporting");await store.transition("j","completed")
 with pytest.raises(JobStateConflict):await store.update("j",progress=1)
 with pytest.raises(JobStateConflict):await store.transition("j","validating")
