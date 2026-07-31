from dataclasses import asdict

from fastapi import APIRouter, Depends, Request

from app.core.config import get_settings
from app.core.security import require_api_key

router = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])


@router.get("/formats")
async def formats(request: Request):
    return {"formats": request.app.state.exporters.formats()}


@router.get("/model")
async def model(request: Request):
    profile = request.app.state.profiles.get(get_settings().default_model_profile)
    info = await request.app.state.backends.get(profile.backend).get_model_info(profile.model)
    return asdict(info)


@router.get("/model/profiles")
async def profiles(request: Request):
    return {"profiles": request.app.state.profiles.public()}


@router.get("/config/public")
async def public_config():
    s = get_settings()
    return {
        "max_upload_size": s.max_upload_size,
        "max_pages": s.max_pages,
        "default_profile": s.default_model_profile,
        "dpi": s.pdf_render_dpi,
        "backend": s.vision_backend,
    }
