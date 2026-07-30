import json,time,uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse
from app.api.routes import router
from app.core.config import get_settings
from app.core.exceptions import ServiceError
from app.core.metrics import ERRORS,REQUESTS
from app.core.logging import configure_logging
from app.services.vision.profiles import load_profiles
from app.services.recognition.pipeline import RecognitionPipeline
from app.services.vision.registry import create_backend
@asynccontextmanager
async def lifespan(app):
    s=get_settings(); configure_logging(s.log_level); app.state.profiles=load_profiles(s.profile_dir); s.temp_dir.mkdir(parents=True,exist_ok=True); s.result_dir.mkdir(parents=True,exist_ok=True)
    app.state.backend=create_backend(s); app.state.pipeline=RecognitionPipeline(s,app.state.backend)
    yield
    client=getattr(app.state.backend,"client",None)
    if client: await client.aclose()
app=FastAPI(title="Local Vision OCR",version="1.0.0",lifespan=lifespan)
@app.middleware("http")
async def request_context(request:Request,call_next):
    request.state.request_id=request.headers.get("X-Request-ID") or str(uuid.uuid4()); started=time.monotonic()
    response=await call_next(request); response.headers["X-Request-ID"]=request.state.request_id
    REQUESTS.labels(request.url.path,response.status_code).inc(); return response
@app.exception_handler(ServiceError)
async def service_error(request,exc):
    ERRORS.labels(exc.code).inc(); return JSONResponse({"error":{"code":exc.code,"message":exc.message,"details":exc.details,"request_id":getattr(request.state,"request_id","")}},status_code=exc.status_code)
@app.exception_handler(Exception)
async def internal_error(request,exc):
    ERRORS.labels("internal_error").inc(); return JSONResponse({"error":{"code":"internal_error","message":"Internal service error","details":{},"request_id":getattr(request.state,"request_id","")}},status_code=500)
app.include_router(router)
