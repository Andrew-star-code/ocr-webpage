import asyncio,shutil,time
from fastapi import APIRouter,Depends,File,Form,Request,UploadFile
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST,generate_latest
from redis.asyncio import Redis
from app.core.config import get_settings
from app.core.security import require_api_key
from app.services.exporters.all import EXPORTERS,MIMES
router=APIRouter()
@router.get("/health")
async def health(): return {"status":"healthy"}
@router.get("/ready")
async def ready(request:Request):
    s=get_settings(); checks={}; redis=Redis.from_url(s.redis_url)
    try: checks["redis"]=bool(await redis.ping())
    except Exception: checks["redis"]=False
    checks["storage"]=shutil.disk_usage(s.temp_dir.parent).free>=s.min_free_storage_bytes
    h=await request.app.state.backend.healthcheck(); checks["vision_backend"]=h.healthy
    try: info=await request.app.state.backend.get_model_info(); checks.update(model_present=True,vision_capable=info.vision_capable,structured_output=info.structured_output)
    except Exception: checks.update(model_present=False,vision_capable=False,structured_output=False)
    checks["worker"]=checks["redis"]
    return Response(content=__import__("json").dumps({"ready":all(checks.values()),"checks":checks}),media_type="application/json",status_code=200 if all(checks.values()) else 503)
@router.get("/metrics")
async def metrics(): return Response(generate_latest(),media_type=CONTENT_TYPE_LATEST)
@router.get("/v1/formats",dependencies=[Depends(require_api_key)])
async def formats(): return {"formats":["json","docx","txt","md","html","searchable_pdf"]}
@router.get("/v1/model",dependencies=[Depends(require_api_key)])
async def model(request:Request): return (await request.app.state.backend.get_model_info()).__dict__
@router.get("/v1/model/profiles",dependencies=[Depends(require_api_key)])
async def profiles(): return {"profiles":["default","glm_ocr","qwen_vl","generic_vision","custom_ollama","custom_llama_cpp"]}
@router.get("/v1/config/public",dependencies=[Depends(require_api_key)])
async def public_config():
    s=get_settings(); return {"max_upload_size":s.max_upload_size,"max_pages":s.max_pages,"default_profile":s.default_model_profile,"dpi":s.pdf_render_dpi,"backend":s.vision_backend}
@router.post("/v1/ocr",dependencies=[Depends(require_api_key)])
async def ocr(request:Request,file:UploadFile=File(...),output_format:str=Form("json"),language:str=Form("rus+eng"),model_profile:str=Form("default"),preserve_layout:bool=Form(True),detect_tables:bool=Form(True),preprocess_mode:str=Form("auto"),normalize_text:bool=Form(False),include_bounding_boxes:bool=Form(True),include_processing_metadata:bool=Form(True),allow_partial_result:bool=Form(False),dpi:int=Form(300,ge=150,le=450)):
    if output_format not in EXPORTERS: from app.core.exceptions import ServiceError; raise ServiceError("invalid_request","Unknown output format")
    started=time.monotonic(); data=await file.read(get_settings().max_upload_size+1)
    doc=await request.app.state.pipeline.run(data,language,model_profile,preprocess_mode,normalize_text,detect_tables,dpi,allow_partial_result)
    body=EXPORTERS[output_format](doc); elapsed=time.monotonic()-started
    headers={"X-Request-ID":request.state.request_id,"X-Processing-Time":f"{elapsed:.3f}","X-Page-Count":str(len(doc.pages))}
    if output_format!="json": headers["Content-Disposition"]=f'attachment; filename="result.{output_format}"'
    return Response(body,media_type=MIMES[output_format],headers=headers)

@router.post("/v1/jobs",dependencies=[Depends(require_api_key)])
async def create_job(file:UploadFile=File(...),output_format:str=Form("json"),language:str=Form("rus+eng"),model_profile:str=Form("default"),detect_tables:bool=Form(True),preprocess_mode:str=Form("auto"),normalize_text:bool=Form(False),allow_partial_result:bool=Form(False),dpi:int=Form(300,ge=150,le=450)):
    import uuid
    from app.services.jobs.store import JobStore
    from app.workers.tasks import recognize_job
    s=get_settings(); redis=Redis.from_url(s.redis_url); queued=int(await redis.llen("dramatiq:default"))
    if queued>=s.max_queue_size:
        from app.core.exceptions import ServiceError
        raise ServiceError("queue_is_full","Processing queue is full",429)
    data=await file.read(s.max_upload_size+1); from app.services.validation.files import validate_document; validate_document(data,s)
    job_id=str(uuid.uuid4()); options={"output_format":output_format,"language":language,"model_profile":model_profile,"detect_tables":detect_tables,"preprocess_mode":preprocess_mode,"normalize_text":normalize_text,"allow_partial_result":allow_partial_result,"dpi":dpi}
    value=await JobStore(s.redis_url,s.result_ttl_seconds).create(job_id,options); await redis.set(f"ocr:input:{job_id}",data,ex=s.temp_file_ttl_seconds); recognize_job.send(job_id)
    return {k:value[k] for k in ("job_id","status","created_at")}
@router.get("/v1/jobs/{job_id}",dependencies=[Depends(require_api_key)])
async def job_status(job_id:str):
    from app.services.jobs.store import JobStore
    value=await JobStore(get_settings().redis_url,get_settings().result_ttl_seconds).get(job_id)
    if not value:
        from app.core.exceptions import ServiceError
        raise ServiceError("job_not_found","Job not found",404)
    value.pop("options",None); return value
@router.get("/v1/jobs/{job_id}/result",dependencies=[Depends(require_api_key)])
async def job_result(job_id:str):
    from app.services.jobs.store import JobStore
    s=get_settings(); value=await JobStore(s.redis_url,s.result_ttl_seconds).get(job_id)
    if not value:
        from app.core.exceptions import ServiceError
        raise ServiceError("job_not_found","Job not found",404)
    if value["status"] not in {"completed","completed_with_warnings"}:
        from app.core.exceptions import ServiceError
        raise ServiceError("invalid_request","Result is not ready",409)
    body=await Redis.from_url(s.redis_url).get(f"ocr:result:{job_id}"); fmt=value["options"]["output_format"]
    if body is None:
        from app.core.exceptions import ServiceError
        raise ServiceError("result_expired","Result expired",410)
    return Response(body,media_type=MIMES[fmt],headers={"Content-Disposition":f'attachment; filename="result.{fmt}"'})
@router.post("/v1/jobs/{job_id}/cancel",dependencies=[Depends(require_api_key)])
async def cancel_job(job_id:str):
    from app.services.jobs.store import JobStore
    store=JobStore(get_settings().redis_url,get_settings().result_ttl_seconds); value=await store.update(job_id,status="cancelled",stage="cancelled")
    if not value:
        from app.core.exceptions import ServiceError
        raise ServiceError("job_not_found","Job not found",404)
    return {"job_id":job_id,"status":"cancelled"}
@router.delete("/v1/jobs/{job_id}",dependencies=[Depends(require_api_key)])
async def delete_job(job_id:str):
    from app.services.jobs.store import JobStore
    if not await JobStore(get_settings().redis_url,get_settings().result_ttl_seconds).delete(job_id):
        from app.core.exceptions import ServiceError
        raise ServiceError("job_not_found","Job not found",404)
    return Response(status_code=204)
