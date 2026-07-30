import uuid
from fastapi import APIRouter,Depends,File,Form,Request,UploadFile
from fastapi.responses import Response
from redis.asyncio import Redis
from app.api.utils import disposition,read_upload
from app.core.config import get_settings
from app.core.exceptions import ServiceError
from app.core.security import require_api_key
from app.services.jobs.store import JobStore
from app.services.jobs.capacity import QueueCapacity
from app.services.validation.files import validate_document
router=APIRouter(prefix="/v1/jobs",dependencies=[Depends(require_api_key)])
@router.post("")
async def create_job(request:Request,file:UploadFile=File(...),output_format:str=Form("json"),language:str=Form("rus+eng",max_length=32),model_profile:str=Form("default",max_length=64),preserve_layout:bool=Form(True),detect_tables:bool=Form(True),preprocess_mode:str=Form("auto"),normalize_text:bool=Form(False),include_bounding_boxes:bool=Form(True),include_processing_metadata:bool=Form(True),allow_partial_result:bool=Form(False),dpi:int=Form(300,ge=150,le=450)):
 exporter=request.app.state.exporters.get(output_format)
 if not exporter:raise ServiceError("invalid_request","Unknown output format",400)
 request.app.state.profiles.get(model_profile)
 if preprocess_mode not in {"none","safe","enhanced","auto"}:raise ServiceError("invalid_request","Invalid preprocess mode",422)
 s=get_settings();redis=Redis.from_url(s.redis_url,decode_responses=True);store=JobStore(s.redis_url,s.result_ttl_seconds,redis);capacity=QueueCapacity(redis,s.max_queue_size);job_id=str(uuid.uuid4());stored=None
 try:
  if not await capacity.reserve(job_id):raise ServiceError("queue_is_full","Processing queue is full",429)
  data=await read_upload(file,s.max_upload_size);mime=validate_document(data,s);stored=await request.app.state.storage.save_input(job_id,data,mime);await request.app.state.storage.tag_job_file(job_id,stored)
  options={"output_format":output_format,"language":language,"model_profile":model_profile,"preserve_layout":preserve_layout,"detect_tables":detect_tables,"preprocess_mode":preprocess_mode,"normalize_text":normalize_text,"include_bounding_boxes":include_bounding_boxes,"include_processing_metadata":include_processing_metadata,"allow_partial_result":allow_partial_result,"dpi":dpi}
  value=await store.create(job_id,options,stored.identifier)
  try:
   from app.workers.tasks import recognize_job
   recognize_job.send(job_id)
  except Exception:
   await store.delete(job_id);await request.app.state.storage.delete_job_files(job_id);await capacity.release(job_id);raise ServiceError("queue_dispatch_failed","Could not dispatch job",503)
  return {k:value[k] for k in ("job_id","status","created_at","version")}
 except Exception:
  if stored and not await store.get(job_id):await request.app.state.storage.delete_job_files(job_id)
  await capacity.release(job_id) if not await store.get(job_id) else _noop()
  raise
 finally:await redis.aclose()
async def _noop():return None
@router.get("/{job_id}")
async def status(job_id:str):
 store=JobStore(get_settings().redis_url,get_settings().result_ttl_seconds)
 try:
  value=await store.get(job_id)
  if not value:raise ServiceError("job_not_found","Job not found",404)
  return {k:v for k,v in value.items() if k not in {"options","input_file","result_file"}}
 finally:await store.close()
@router.get("/{job_id}/result")
async def result(request:Request,job_id:str):
 store=JobStore(get_settings().redis_url,get_settings().result_ttl_seconds)
 try:
  value=await store.get(job_id)
  if not value:raise ServiceError("job_not_found","Job not found",404)
  if value["status"] not in {"completed","completed_with_warnings"}:raise ServiceError("invalid_request","Result is not ready",409)
  if not value["result_file"]:raise ServiceError("result_expired","Result expired",410)
  body=await request.app.state.storage.read_result(value["result_file"]);exporter=request.app.state.exporters.get(value["options"]["output_format"])
  return Response(body,media_type=exporter.mime_type,headers={"Content-Disposition":disposition(exporter.extension)})
 finally:await store.close()
@router.post("/{job_id}/cancel")
async def cancel(job_id:str):
 store=JobStore(get_settings().redis_url,get_settings().result_ttl_seconds)
 try:
  value=await store.transition(job_id,"cancelled",stage="cancelled")
  if not value:raise ServiceError("job_not_found","Job not found",404)
  return {"job_id":job_id,"status":"cancelled"}
 finally:await store.close()
@router.delete("/{job_id}",status_code=204)
async def delete(request:Request,job_id:str):
 store=JobStore(get_settings().redis_url,get_settings().result_ttl_seconds)
 try:
  if not await store.delete(job_id):raise ServiceError("job_not_found","Job not found",404)
  await QueueCapacity(store.redis,get_settings().max_queue_size).release(job_id);await request.app.state.storage.delete_job_files(job_id);return Response(status_code=204)
 finally:await store.close()
