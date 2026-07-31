import json

import httpx
import pytest

from app.services.vision.base import VisionRequestOptions
from app.services.vision.llama_cpp import LlamaCppVisionBackend


@pytest.mark.asyncio
async def test_model_presence_does_not_claim_vision_before_probe():
    async def handler(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "vision-model"}]})
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend = LlamaCppVisionBackend("http://local", "vision-model", client=client)
    info = await backend.get_model_info()
    assert info.present
    assert not info.vision_capable
    assert not info.structured_output
    await backend.close()


@pytest.mark.asyncio
async def test_successful_structured_multimodal_probe_updates_capabilities():
    async def handler(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "vision-model"}]})
        payload = json.loads(request.content)
        assert payload["response_format"]["type"] == "json_schema"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"text":"OCR"}'}, "finish_reason": "stop"}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend = LlamaCppVisionBackend("http://local", "vision-model", client=client)
    response = await backend.recognize_page(
        b"image",
        "read",
        {"type": "object"},
        VisionRequestOptions("vision-model", supports_json_schema=True),
    )
    assert json.loads(response.content)["text"] == "OCR"
    info = await backend.get_model_info()
    assert info.present and info.vision_capable and info.structured_output
    await backend.close()


@pytest.mark.asyncio
async def test_missing_models_endpoint_reports_model_absent():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    backend = LlamaCppVisionBackend("http://local", "missing", client=client)
    info = await backend.get_model_info()
    assert not info.present
    assert not info.vision_capable
    await backend.close()
