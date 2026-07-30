from dataclasses import dataclass
from typing import Protocol
@dataclass
class VisionRequestOptions:
    temperature: float=0; seed: int=42; num_ctx: int=32768; num_predict: int=12000
@dataclass
class VisionResponse:
    content: str; done_reason: str | None=None; prompt_tokens: int=0; completion_tokens: int=0
@dataclass
class BackendHealth: healthy: bool; detail: str
@dataclass
class ModelInfo: name: str; vision_capable: bool; structured_output: bool
class VisionBackend(Protocol):
    async def recognize_page(self, image: bytes, prompt: str, json_schema: dict, options: VisionRequestOptions) -> VisionResponse: ...
    async def healthcheck(self) -> BackendHealth: ...
    async def get_model_info(self) -> ModelInfo: ...
    async def warmup(self) -> None: ...
