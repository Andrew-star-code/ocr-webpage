from fastapi import APIRouter

from app.api.routes.health import router as health
from app.api.routes.jobs import router as jobs
from app.api.routes.models import router as models
from app.api.routes.ocr import router as ocr

router = APIRouter()
for item in (health, ocr, jobs, models):
    router.include_router(item)
