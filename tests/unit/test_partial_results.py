import asyncio
from types import MethodType, SimpleNamespace

import pytest

from app.core.config import Settings
from app.core.exceptions import ServiceError
from app.schemas.recognition import PageRecognition, ParagraphBlock
from app.services.recognition import pipeline as pipeline_module
from app.services.recognition.pipeline import RecognitionPipeline
from app.services.rendering.pages import RenderedPage
from app.services.vision.profiles import ProfileRegistry


def _page(number):
    return PageRecognition(
        page_number=number,
        width=100,
        height=100,
        blocks=[
            ParagraphBlock(id=f"raw-{number}", reading_order=1, original_text=f"page {number}")
        ],
    )


def _pipeline(monkeypatch, failing_pages):
    settings = Settings()
    profiles = ProfileRegistry.load(settings.profile_dir)
    backend_registry = SimpleNamespace(backends={"ollama": object()})
    pipeline = RecognitionPipeline(settings, backend_registry, profiles)
    rendered = [RenderedPage(number, b"image", 100, 100, 300, 0) for number in range(1, 4)]
    monkeypatch.setattr(pipeline_module, "validate_document", lambda data, settings: "image/png")
    monkeypatch.setattr(pipeline_module, "render_pages", lambda data, mime, dpi: rendered)

    async def process(self, source, profile, language, mode, tables, cancel):
        if source.number in failing_pages:
            raise ServiceError("invalid_model_response", "Page recognition failed", 502)
        return _page(source.number), 0, {}, []

    pipeline._process_page = MethodType(process, pipeline)
    return pipeline


def test_partial_result_preserves_successful_pages(monkeypatch):
    pipeline = _pipeline(monkeypatch, {2})
    result = asyncio.run(pipeline.run(b"document", allow_partial=True))
    assert [page.page_number for page in result.document.pages] == [1, 3]
    assert result.document.partial
    assert result.document.page_failures[0].page_number == 2
    assert result.document.page_failures[0].code == "invalid_model_response"


def test_partial_false_is_fail_fast(monkeypatch):
    pipeline = _pipeline(monkeypatch, {2})
    with pytest.raises(ServiceError, match="Page recognition failed"):
        asyncio.run(pipeline.run(b"document", allow_partial=False))


def test_all_failed_pages_do_not_create_empty_success(monkeypatch):
    pipeline = _pipeline(monkeypatch, {1, 2, 3})
    with pytest.raises(ServiceError) as error:
        asyncio.run(pipeline.run(b"document", allow_partial=True))
    assert error.value.code == "invalid_model_response"
