import time,uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse
from app.api.routes import router
from app.core.config import get_settings
from app.core.exceptions import ServiceError
from app.core.logging import configure_logging
from app.core.metrics import ERRORS,REQUESTS
from app.core.rate_limit import RedisRateLimiter
from app.services.exporters.registry import ExporterRegistry
from app.services.recognition.pipeline import RecognitionPipeline
from app.services.storage.local import LocalDocumentStorage
from app.services.vision.profiles import ProfileRegistry
from app.services.vision.registry import create_backends
@asynccontextmanager
async def lifespan(app):
 s=get_settings();configure_logging(s.log_level);app.state.profiles=ProfileRegistry.load(s.profile_dir);app.state.backends=create_backends(s);app.state.storage=LocalDocumentStorage(s.temp_dir,s.result_dir,s.temp_file_ttl_seconds,s.result_ttl_seconds);app.state.exporters=ExporterRegistry();app.state.pipeline=RecognitionPipeline(s,app.state.backends,app.state.profiles);app.state.readiness_cache=None;app.state.rate_limiter=RedisRateLimiter(s)
 yield
 await app.state.backends.close();await app.state.rate_limiter.close()
app=FastAPI(title="Local Vision OCR",version="1.1.0",lifespan=lifespan)
@app.middleware("http")
async def context(request:Request,call_next):
 request.state.request_id=request.headers.get("X-Request-ID") or str(uuid.uuid4())
 limited=await request.app.state.rate_limiter.check(request)
 if limited:return limited
 response=await call_next(request);response.headers["X-Request-ID"]=request.state.request_id;REQUESTS.labels(request.url.path,response.status_code).inc();return response
@app.exception_handler(ServiceError)
async def service_error(request,exc):ERRORS.labels(exc.code).inc();return JSONResponse({"error":{"code":exc.code,"message":exc.message,"details":exc.details,"request_id":getattr(request.state,"request_id","")}},status_code=exc.status_code)
@app.exception_handler(Exception)
async def internal_error(request,exc):ERRORS.labels("internal_error").inc();return JSONResponse({"error":{"code":"internal_error","message":"Internal service error","details":{},"request_id":getattr(request.state,"request_id","")}},status_code=500)
app.include_router(router)
