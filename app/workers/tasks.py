import asyncio
import threading
import time

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import Middleware
from redis import Redis as SyncRedis
from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.exceptions import ServiceError
from app.core.redis_lock import RedisLock
from app.services.exporters.base import ExportOptions
from app.services.exporters.registry import ExporterRegistry
from app.services.jobs.capacity import QueueCapacity
from app.services.jobs.store import JobStore
from app.services.recognition.pipeline import ProcessingCancelled, RecognitionPipeline
from app.services.storage.cleanup import StorageCleanup
from app.services.storage.local import LocalDocumentStorage
from app.services.vision.profiles import ProfileRegistry
from app.services.vision.registry import create_backends

s = get_settings()


def _heartbeat():
    redis = SyncRedis.from_url(s.redis_url)
    while True:
        try:
            redis.set("ocr:worker:heartbeat", str(time.time()), ex=s.worker_heartbeat_ttl * 2)
        except Exception:
            time.sleep(2)
        time.sleep(max(2, s.worker_heartbeat_ttl // 3))


def _cleanup_loop():
    while True:

        async def clean():
            redis = Redis.from_url(s.redis_url, decode_responses=True)
            storage = LocalDocumentStorage(
                s.temp_dir, s.result_dir, s.temp_file_ttl_seconds, s.result_ttl_seconds
            )
            try:
                await StorageCleanup(redis, storage, s.cleanup_lock_ttl_seconds).run_once()
                await QueueCapacity(
                    redis, s.max_queue_size, s.document_processing_timeout
                ).reconcile()
            finally:
                await redis.aclose()

        try:
            asyncio.run(clean())
        except Exception:
            time.sleep(5)
        time.sleep(s.cleanup_interval_seconds)


class HeartbeatMiddleware(Middleware):
    def after_worker_boot(self, broker, worker):
        threading.Thread(target=_heartbeat, daemon=True, name="ocr-heartbeat").start()
        threading.Thread(target=_cleanup_loop, daemon=True, name="ocr-cleanup").start()


broker = RedisBroker(url=s.redis_url)
broker.add_middleware(HeartbeatMiddleware())
dramatiq.set_broker(broker)


@dramatiq.actor(max_retries=0, time_limit=s.document_processing_timeout * 1000)
def recognize_job(job_id):
    asyncio.run(run(job_id))


async def _publish_result(storage, store, job_id, stored, target, page_count):
    await storage.tag_job_file(job_id, stored)
    completed = await store.complete(
        job_id,
        target,
        result_file=stored.identifier,
        current_page=page_count,
        total_pages=page_count,
        progress=100,
    )
    if not completed or completed["status"] not in {
        "completed",
        "completed_with_warnings",
    }:
        await storage.delete_file(stored.identifier)
        await storage.delete_reference(job_id, stored.identifier)
        raise ProcessingCancelled()
    return completed


async def run(job_id):
    redis = Redis.from_url(s.redis_url, decode_responses=True)
    store = JobStore(s.redis_url, s.job_metadata_ttl_seconds, redis)
    capacity = QueueCapacity(redis, s.max_queue_size, s.document_processing_timeout)
    storage = LocalDocumentStorage(
        s.temp_dir, s.result_dir, s.temp_file_ttl_seconds, s.result_ttl_seconds
    )
    backends = create_backends(s)
    profiles = ProfileRegistry.load(s.profile_dir)
    pipeline = RecognitionPipeline(s, backends, profiles)
    lock = RedisLock(redis, f"ocr:worker-lock:{job_id}", s.worker_lock_ttl_seconds)
    if not await lock.acquire():
        await backends.close()
        await redis.aclose()
        return

    stop_renewal = asyncio.Event()
    ownership_lost = asyncio.Event()
    renewal = asyncio.create_task(
        lock.renew_until_stopped(stop_renewal, ownership_lost, s.worker_lock_renew_interval_seconds)
    )
    created_results = []

    async def cancelled():
        current = await store.get(job_id)
        return not current or current["status"] == "cancelled" or ownership_lost.is_set()

    async def ensure_active():
        if await cancelled():
            raise ProcessingCancelled()

    async def progress(stage, current, total, retries):
        await ensure_active()
        target = "rendering" if stage == "rendering" else "recognizing"
        result = await store.update_progress(
            job_id,
            target,
            stage=stage,
            current_page=current,
            total_pages=total,
            progress=round(current / total * 100, 1) if total else 0,
            retry_count=retries,
        )
        if result and result["status"] == "cancelled":
            raise ProcessingCancelled()

    try:
        job = await store.get(job_id)
        if not job or job["status"] != "queued":
            return
        await store.transition(job_id, "validating", expected_status="queued", stage="storage_read")
        await ensure_active()
        data = await storage.read_input(job["input_file"])
        options = job["options"]
        result = await pipeline.run(
            data,
            options["language"],
            options["model_profile"],
            options["preprocess_mode"],
            options["normalize_text"],
            options["detect_tables"],
            options["dpi"],
            progress,
            cancelled,
        )
        await ensure_active()
        current = await store.get(job_id)
        await store.transition(
            job_id, "exporting", expected_status=current["status"], stage="exporting"
        )
        exporter = ExporterRegistry().get(options["output_format"])
        body = exporter.export(
            result,
            ExportOptions(
                options["preserve_layout"],
                options["include_bounding_boxes"],
                options["include_processing_metadata"],
            ),
        )
        await ensure_active()
        stored = await storage.save_result(job_id, body, exporter.mime_type, exporter.extension)
        created_results.append(stored.identifier)
        await ensure_active()
        target = (
            "completed_with_warnings"
            if result.document.partial or result.document.warnings
            else "completed"
        )
        await _publish_result(storage, store, job_id, stored, target, len(result.document.pages))
        created_results.clear()
    except ProcessingCancelled:
        await store.cancel(job_id)
    except ServiceError as exc:
        await store.fail(job_id, {"code": exc.code, "message": exc.message, "details": exc.details})
    except Exception:
        await store.fail(job_id, {"code": "internal_error", "message": "Internal processing error"})
    finally:
        for identifier in created_results:
            await storage.delete_file(identifier)
            await storage.delete_reference(job_id, identifier)
        job = await store.get(job_id)
        if job and job.get("input_file"):
            await storage.delete_file(job["input_file"])
        await capacity.release(job_id)
        stop_renewal.set()
        await renewal
        await lock.release()
        await backends.close()
        await redis.aclose()
