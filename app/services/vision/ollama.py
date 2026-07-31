import asyncio
import base64
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from app.core.exceptions import ServiceError
from app.core.metrics import VISION_RETRIES, VISION_TIMEOUTS
from app.services.vision.base import BackendHealth, ModelInfo, VisionResponse

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class OllamaVisionBackend:
    name = "ollama"

    def __init__(
        self,
        base_url,
        model,
        timeout=600,
        connect_timeout=10,
        keep_alive=-1,
        concurrency=1,
        max_retries=2,
        client=None,
    ):
        self.base_url = base_url.rstrip("/")
        self.default_model = model
        self.keep_alive = keep_alive
        self.sem = asyncio.Semaphore(concurrency)
        self.max_retries = max_retries
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=connect_timeout)
        )

    def _delay(self, attempt, response=None):
        if response is not None and response.headers.get("Retry-After"):
            value = response.headers["Retry-After"]
            try:
                return min(float(value), 30)
            except ValueError:
                try:
                    return max(
                        0,
                        min(
                            (
                                parsedate_to_datetime(value) - datetime.now(timezone.utc)
                            ).total_seconds(),
                            30,
                        ),
                    )
                except (TypeError, ValueError):
                    return 0
        return min(0.5 * (2**attempt) + random.uniform(0, 0.2), 8)

    async def recognize_page(self, image, prompt, json_schema, options):
        payload = {
            "model": options.model or self.default_model,
            "messages": [
                {"role": "system", "content": options.system_prompt},
                {
                    "role": "user",
                    "content": prompt,
                    "images": [base64.b64encode(image).decode("ascii")],
                },
            ],
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": options.temperature,
                "seed": options.seed,
                "num_ctx": options.num_ctx,
                "num_predict": options.num_predict,
            },
        }
        if options.supports_json_schema:
            payload["format"] = json_schema
        for attempt in range(self.max_retries + 1):
            response = None
            try:
                async with self.sem:
                    response = await self.client.post(f"{self.base_url}/api/chat", json=payload)
                if response.status_code not in _RETRYABLE_STATUS:
                    if 400 <= response.status_code < 500:
                        code = (
                            "model_not_found"
                            if response.status_code == 404
                            else "vision_inference_failed"
                        )
                        raise ServiceError(
                            code,
                            "Ollama rejected the request",
                            503 if response.status_code == 404 else 502,
                            {"status": response.status_code},
                        )
                    response.raise_for_status()
                    data = response.json()
                    content = data.get("message", {}).get("content", "")
                    if content.strip():
                        return VisionResponse(
                            content,
                            data.get("done_reason"),
                            data.get("prompt_eval_count", 0),
                            data.get("eval_count", 0),
                        )
                    reason = "empty_response"
                    error = ServiceError(
                        "invalid_model_response", "Ollama returned an empty response", 502
                    )
                    if attempt >= self.max_retries:
                        raise error
                    VISION_RETRIES.labels(reason).inc()
                    await asyncio.sleep(self._delay(attempt, response))
                    continue
                reason = (
                    "rate_limited"
                    if response.status_code == 429
                    else f"http_{response.status_code}"
                )
                error = ServiceError(
                    "vision_rate_limited"
                    if response.status_code == 429
                    else "vision_inference_failed",
                    "Retryable Ollama response",
                    429 if response.status_code == 429 else 502,
                    {"status": response.status_code},
                )
            except (httpx.ConnectTimeout, httpx.ReadTimeout):
                VISION_TIMEOUTS.inc()
                reason = "timeout"
                error = ServiceError("vision_request_timeout", "Vision request timed out", 504)
            except httpx.ConnectError:
                reason = "connection"
                error = ServiceError("ollama_unavailable", "Ollama is unavailable", 503)
            except ServiceError:
                raise
            except (httpx.HTTPError, ValueError):
                reason = "transport"
                error = ServiceError("vision_inference_failed", "Ollama transport failed", 502)
            if attempt >= self.max_retries:
                raise error
            VISION_RETRIES.labels(reason).inc()
            await asyncio.sleep(self._delay(attempt, response))
        raise ServiceError("vision_inference_failed", "Ollama inference failed", 502)

    async def healthcheck(self):
        try:
            return BackendHealth(
                (await self.client.get(f"{self.base_url}/api/tags")).is_success, "ollama"
            )
        except httpx.HTTPError:
            return BackendHealth(False, "unreachable")

    async def get_model_info(self, model=None):
        name = model or self.default_model
        response = await self.client.post(f"{self.base_url}/api/show", json={"model": name})
        if response.status_code == 404:
            raise ServiceError("model_not_found", "Configured model is not installed", 503)
        response.raise_for_status()
        caps = response.json().get("capabilities", [])
        return ModelInfo(
            name=name, present=True, vision_capable="vision" in caps, structured_output=True
        )

    async def warmup(self):
        await self.get_model_info()

    async def close(self):
        await self.client.aclose()
