import asyncio
import base64
import random

import httpx

from app.core.exceptions import ServiceError
from app.core.metrics import VISION_RETRIES, VISION_TIMEOUTS
from app.services.vision.base import BackendHealth, ModelInfo, VisionResponse


class LlamaCppVisionBackend:
    name = "llama_cpp"

    def __init__(self, base_url, model, timeout=600, concurrency=1, max_retries=2, client=None):
        self.base_url = base_url.rstrip("/")
        self.default_model = model
        self.client = client or httpx.AsyncClient(timeout=timeout)
        self.sem = asyncio.Semaphore(concurrency)
        self.max_retries = max_retries
        self._structured_verified = False
        self._vision_verified = False

    def _delay(self, attempt, response=None):
        if response is not None:
            try:
                return min(float(response.headers.get("Retry-After", "")), 30)
            except ValueError:
                None
        return min(0.5 * 2**attempt + random.uniform(0, 0.2), 8)

    async def recognize_page(self, image, prompt, json_schema, options):
        content = [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {
                    "url": "data:image/png;base64," + base64.b64encode(image).decode("ascii")
                },
            },
        ]
        messages = (
            [{"role": "system", "content": options.system_prompt}] if options.system_prompt else []
        ) + [{"role": "user", "content": content}]
        data = {
            "model": options.model or self.default_model,
            "messages": messages,
            "temperature": options.temperature,
            "seed": options.seed,
            "max_tokens": options.num_predict,
        }
        if options.supports_json_schema:
            data["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "page", "schema": json_schema},
            }
        for attempt in range(self.max_retries + 1):
            response = None
            try:
                async with self.sem:
                    response = await self.client.post(
                        f"{self.base_url}/v1/chat/completions", json=data
                    )
                if response.status_code in {429, 500, 502, 503, 504}:
                    reason = (
                        "rate_limited"
                        if response.status_code == 429
                        else f"http_{response.status_code}"
                    )
                    error = ServiceError(
                        "vision_rate_limited"
                        if response.status_code == 429
                        else "vision_inference_failed",
                        "Retryable llama.cpp response",
                        429 if response.status_code == 429 else 502,
                    )
                elif 400 <= response.status_code < 500:
                    raise ServiceError(
                        "vision_inference_failed",
                        "llama.cpp rejected request",
                        502,
                        {"status": response.status_code},
                    )
                else:
                    response.raise_for_status()
                    body = response.json()
                    choice = body["choices"][0]
                    text = choice.get("message", {}).get("content", "")
                    finish = choice.get("finish_reason")
                    if finish in {"length", "max_tokens"}:
                        raise ServiceError("output_truncated", "llama.cpp output truncated", 502)
                    if not text.strip():
                        reason = "empty_response"
                        error = ServiceError(
                            "invalid_model_response", "llama.cpp returned empty output", 502
                        )
                    else:
                        self._vision_verified = True
                        self._structured_verified = (
                            self._structured_verified or options.supports_json_schema
                        )
                        return VisionResponse(
                            text,
                            finish,
                            body.get("usage", {}).get("prompt_tokens", 0),
                            body.get("usage", {}).get("completion_tokens", 0),
                        )
            except (httpx.ConnectTimeout, httpx.ReadTimeout):
                VISION_TIMEOUTS.inc()
                reason = "timeout"
                error = ServiceError("vision_request_timeout", "llama.cpp request timed out", 504)
            except httpx.ConnectError:
                reason = "connection"
                error = ServiceError("llama_cpp_unavailable", "llama.cpp is unavailable", 503)
            except ServiceError:
                raise
            except (httpx.HTTPError, ValueError, KeyError, IndexError):
                reason = "transport"
                error = ServiceError("vision_inference_failed", "llama.cpp inference failed", 502)
            if attempt >= self.max_retries:
                raise error
            VISION_RETRIES.labels(reason).inc()
            await asyncio.sleep(self._delay(attempt, response))
        raise ServiceError("vision_inference_failed", "llama.cpp inference failed", 502)

    async def healthcheck(self):
        try:
            response = await self.client.get(f"{self.base_url}/health")
            return BackendHealth(response.is_success, "llama.cpp")
        except httpx.HTTPError:
            return BackendHealth(False, "unreachable")

    async def get_model_info(self, model=None):
        name = model or self.default_model
        try:
            response = await self.client.get(f"{self.base_url}/v1/models")
            response.raise_for_status()
            models = [item.get("id") for item in response.json().get("data", [])]
            present = name in models
        except (httpx.HTTPError, ValueError):
            present = False
        return ModelInfo(name, self._vision_verified, self._structured_verified, present)

    async def warmup(self):
        await self.healthcheck()

    async def close(self):
        await self.client.aclose()
