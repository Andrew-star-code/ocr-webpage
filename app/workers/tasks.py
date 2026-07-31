import asyncio
import logging
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
from app.services.jobs.state_machine import JobStateConflict
from app.services.jobs.store import JobStore
from app.services.recognition.pipeline import ProcessingCancelled, RecognitionPipeline
from app.services.storage.base import DocumentStorage, StoredFile
from app.services.storage.cleanup import StorageCleanup
from app.services.storage.local import LocalDocumentStorage
from app.services.vision.profiles import ProfileRegistry
from app.services.vision.registry import create_backends

s = get_settings()
logger = logging.getLogger(__name__)


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


async def _delete_result_artifacts(storage: DocumentStorage, job_id: str, identifier: str) -> None:
    for operation, callback in (
        ("delete_result", lambda: storage.delete_file(identifier)),
        ("delete_reference", lambda: storage.delete_reference(job_id, identifier)),
    ):
        try:
            await callback()
        except Exception:
            logger.exception(
                "result_artifact_cleanup_failed",
                extra={
                    "job_id": job_id,
                    "storage_identifier": identifier,
                    "error_code": operation,
                },
            )


async def _publish_result(
    storage: DocumentStorage,
    store: JobStore,
    job_id: str,
    stored: StoredFile,
    target_status: str,
    page_count: int,
) -> dict:
    try:
        current = await store.get(job_id)
    except Exception:
        await _delete_result_artifacts(storage, job_id, stored.identifier)
        raise
    if not current or current["status"] == "cancelled":
        await _delete_result_artifacts(storage, job_id, stored.identifier)
        raise ProcessingCancelled()
    if current["status"] in {"failed", "completed", "completed_with_warnings"}:
        await _delete_result_artifacts(storage, job_id, stored.identifier)
        raise JobStateConflict(f"Cannot publish result for terminal job {current['status']}")
    try:
        await storage.tag_job_file(job_id, stored)
        completed = await store.complete(
            job_id,
            target_status,
            result_file=stored.identifier,
            current_page=page_count,
            total_pages=page_count,
            progress=100,
        )
    except Exception:
        await _delete_result_artifacts(storage, job_id, stored.identifier)
        raise
    if not completed or completed["status"] not in {
        "completed",
        "completed_with_warnings",
    }:
        await _delete_result_artifacts(storage, job_id, stored.identifier)
        if not completed or completed["status"] == "cancelled":
            raise ProcessingCancelled()
        raise JobStateConflict(f"Result publication lost to {completed['status']}")
    return completed


async def _safe_worker_cleanup(
    *,
    storage,
    store,
    capacity,
    lock,
    stop_renewal,
    renewal,
    backends,
    redis,
    job_id,
    created_results,
):
    async def attempt(code, callback):
        try:
            await callback()
        except Exception:
            logger.exception(
                "worker_cleanup_failed",
                extra={"job_id": job_id, "error_code": code},
            )

    for identifier in created_results:
        await attempt(
            "delete_result",
            lambda identifier=identifier: _delete_result_artifacts(storage, job_id, identifier),
        )
    job = None
    try:
        job = await store.get(job_id)
    except Exception:
        logger.exception(
            "worker_cleanup_failed", extra={"job_id": job_id, "error_code": "read_job"}
        )
    if job and job.get("input_file"):
        await attempt("delete_input", lambda: storage.delete_file(job["input_file"]))
    await attempt("release_capacity", lambda: capacity.release(job_id))
    stop_renewal.set()
    await attempt("wait_renewal", lambda: renewal)
    await attempt("release_lock", lock.release)
    await attempt("close_backends", backends.close)
    await attempt("close_redis", redis.aclose)


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
            options["allow_partial_result"],
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
        await _safe_worker_cleanup(
            storage=storage,
            store=store,
            capacity=capacity,
            lock=lock,
            stop_renewal=stop_renewal,
            renewal=renewal,
            backends=backends,
            redis=redis,
            job_id=job_id,
            created_results=created_results,
        )
