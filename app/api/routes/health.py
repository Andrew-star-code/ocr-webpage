import asyncio
import io
import json
import shutil
import time

from fastapi import APIRouter, Request
from fastapi.responses import Response
from PIL import Image, ImageDraw
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis.asyncio import Redis

from app.core.config import get_settings
from app.services.vision.base import VisionRequestOptions

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "healthy"}


async def _inference_check(request, profile):
    now = time.monotonic()
    key = (profile.backend, profile.model)
    cached = request.app.state.readiness_cache.get(key)
    if cached and now - cached[0] < get_settings().readiness_cache_ttl:
        return cached[1]
    image = Image.new("RGB", (96, 48), "white")
    ImageDraw.Draw(image).text((8, 12), "OCR 7", fill="black")
    stream = io.BytesIO()
    image.save(stream, "PNG")
    backend = request.app.state.backends.get(profile.backend)
    base_options = dict(
        model=profile.model,
        system_prompt=profile.system_prompt,
        num_ctx=min(profile.num_ctx, 4096),
        num_predict=64,
    )
    vision = False
    structured = False
    try:
        response = await asyncio.wait_for(
            backend.recognize_page(
                stream.getvalue(),
                "Назови кратко видимый текст.",
                {},
                VisionRequestOptions(**base_options, supports_json_schema=False),
            ),
            timeout=30,
        )
        vision = bool(response.content.strip())
        if vision:
            schema = {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            }
            response = await asyncio.wait_for(
                backend.recognize_page(
                    stream.getvalue(),
                    "Верни JSON с полем text, содержащим видимый текст.",
                    schema,
                    VisionRequestOptions(**base_options, supports_json_schema=True),
                ),
                timeout=30,
            )
            value = json.loads(response.content)
            structured = isinstance(value, dict) and bool(value.get("text"))
    except Exception:
        structured = False
    result = {"vision": vision, "structured": structured}
    request.app.state.readiness_cache[key] = (now, result)
    return result


@router.get("/ready")
async def ready(request: Request):
    s = get_settings()
    checks = {}
    redis = Redis.from_url(s.redis_url, decode_responses=True)
    try:
        checks["redis"] = bool(await redis.ping())
        heartbeat = await redis.get("ocr:worker:heartbeat")
        checks["worker"] = bool(
            heartbeat and time.time() - float(heartbeat) <= s.worker_heartbeat_ttl
        )
    except Exception:
        checks.update(redis=False, worker=False)
    finally:
        await redis.aclose()
    checks["storage"] = await request.app.state.storage.healthcheck()
    checks["free_space"] = shutil.disk_usage(s.temp_dir).free >= s.min_free_storage_bytes
    profile = request.app.state.profiles.get(s.default_model_profile)
    backend = request.app.state.backends.get(profile.backend)
    health = await backend.healthcheck()
    checks["vision_backend"] = health.healthy
    try:
        info = await backend.get_model_info(profile.model)
        checks["model_present"] = info.present
    except Exception:
        info = None
        checks["model_present"] = False
    probe = (
        await _inference_check(request, profile)
        if checks["vision_backend"] and checks["model_present"]
        else {"vision": False, "structured": False}
    )
    if probe["vision"]:
        info = await backend.get_model_info(profile.model)
    checks["vision_capable"] = bool(info and (info.vision_capable or probe["vision"]))
    checks["structured_output"] = bool(info and (info.structured_output or probe["structured"]))
    checks["test_inference"] = probe["vision"] and probe["structured"]
    ready = all(checks.values())
    return Response(
        json.dumps({"ready": ready, "checks": checks}),
        status_code=200 if ready else 503,
        media_type="application/json",
    )


@router.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
