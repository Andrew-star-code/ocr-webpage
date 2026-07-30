from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class VisionRequestOptions:
    model: str
    system_prompt: str = ""
    temperature: float = 0
    seed: int = 42
    num_ctx: int = 32768
    num_predict: int = 12000
    supports_json_schema: bool = True


@dataclass(slots=True)
class VisionResponse:
    content: str
    done_reason: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(slots=True)
class BackendHealth:
    healthy: bool
    detail: str


@dataclass(slots=True)
class ModelInfo:
    name: str
    vision_capable: bool
    structured_output: bool
    present: bool = True


class VisionBackend(Protocol):
    name: str

    async def recognize_page(
        self, image: bytes, prompt: str, json_schema: dict, options: VisionRequestOptions
    ) -> VisionResponse: ...
    async def healthcheck(self) -> BackendHealth: ...
    async def get_model_info(self, model: str | None = None) -> ModelInfo: ...
    async def warmup(self) -> None: ...
    async def close(self) -> None: ...
