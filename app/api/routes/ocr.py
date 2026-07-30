import time

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response

from app.api.utils import disposition, read_upload
from app.core.config import get_settings
from app.core.exceptions import ServiceError
from app.core.security import require_api_key
from app.services.exporters.base import ExportOptions

router = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])


@router.post("/ocr")
async def ocr(
    request: Request,
    file: UploadFile = File(...),
    output_format: str = Form("json"),
    language: str = Form("rus+eng", min_length=1, max_length=32),
    model_profile: str = Form("default", min_length=1, max_length=64),
    preserve_layout: bool = Form(True),
    detect_tables: bool = Form(True),
    preprocess_mode: str = Form("auto"),
    normalize_text: bool = Form(False),
    include_bounding_boxes: bool = Form(True),
    include_processing_metadata: bool = Form(True),
    dpi: int = Form(300, ge=150, le=450),
):
    exporter = request.app.state.exporters.get(output_format)
    if not exporter:
        raise ServiceError(
            "invalid_request", "Unknown output format", 400, {"output_format": output_format}
        )
    request.app.state.profiles.get(model_profile)
    if preprocess_mode not in {"none", "safe", "enhanced", "auto"}:
        raise ServiceError("invalid_request", "Invalid preprocess mode", 422)
    started = time.monotonic()
    data = await read_upload(file, get_settings().max_upload_size)
    result = await request.app.state.pipeline.run(
        data,
        language,
        model_profile,
        preprocess_mode,
        normalize_text,
        detect_tables,
        dpi,
    )
    body = exporter.export(
        result, ExportOptions(preserve_layout, include_bounding_boxes, include_processing_metadata)
    )
    elapsed = time.monotonic() - started
    headers = {
        "X-Request-ID": request.state.request_id,
        "X-Processing-Time": f"{elapsed:.3f}",
        "X-Page-Count": str(len(result.document.pages)),
    }
    if output_format != "json":
        headers["Content-Disposition"] = disposition(exporter.extension)
    return Response(body, media_type=exporter.mime_type, headers=headers)
