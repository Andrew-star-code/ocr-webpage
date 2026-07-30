import io,json,shutil,time
from PIL import Image,ImageDraw
from fastapi import APIRouter,Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST,generate_latest
from redis.asyncio import Redis
from app.core.config import get_settings
from app.services.vision.base import VisionRequestOptions
router=APIRouter()
@router.get("/health")
async def health():return {"status":"healthy"}
async def _inference_check(request,profile):
 now=time.monotonic();cached=request.app.state.readiness_cache
 if cached and now-cached[0]<get_settings().readiness_cache_ttl:return cached[1]
 image=Image.new("RGB",(96,48),"white");ImageDraw.Draw(image).text((8,12),"OCR 7",fill="black");stream=io.BytesIO();image.save(stream,"PNG")
 schema={"type":"object","properties":{"text":{"type":"string"}},"required":["text"],"additionalProperties":False}
 try:
  response=await request.app.state.backends.get(profile.backend).recognize_page(stream.getvalue(),"Верни JSON с полем text, содержащим видимый текст.",schema,VisionRequestOptions(profile.model,profile.system_prompt,num_ctx=min(profile.num_ctx,4096),num_predict=64,supports_json_schema=True));value=json.loads(response.content);ok=bool(value.get("text"))
 except Exception:ok=False
 request.app.state.readiness_cache=(now,ok);return ok
@router.get("/ready")
async def ready(request:Request):
 s=get_settings();checks={};redis=Redis.from_url(s.redis_url,decode_responses=True)
 try:
  checks["redis"]=bool(await redis.ping());heartbeat=await redis.get("ocr:worker:heartbeat");checks["worker"]=bool(heartbeat and time.time()-float(heartbeat)<=s.worker_heartbeat_ttl)
 except Exception:checks.update(redis=False,worker=False)
 finally:await redis.aclose()
 checks["storage"]=await request.app.state.storage.healthcheck();checks["free_space"]=shutil.disk_usage(s.temp_dir).free>=s.min_free_storage_bytes
 profile=request.app.state.profiles.get(s.default_model_profile);backend=request.app.state.backends.get(profile.backend);health=await backend.healthcheck();checks["vision_backend"]=health.healthy
 try:info=await backend.get_model_info(profile.model);checks["model_present"]=True;checks["vision_capable"]=info.vision_capable;checks["structured_output"]=info.structured_output
 except Exception:checks.update(model_present=False,vision_capable=False,structured_output=False)
 checks["test_inference"]=await _inference_check(request,profile) if all(checks.get(k) for k in ("vision_backend","model_present","vision_capable","structured_output")) else False
 ready=all(checks.values());return Response(json.dumps({"ready":ready,"checks":checks}),status_code=200 if ready else 503,media_type="application/json")
@router.get("/metrics")
async def metrics():return Response(generate_latest(),media_type=CONTENT_TYPE_LATEST)
