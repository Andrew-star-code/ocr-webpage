from app.core.config import Settings
from app.services.vision.llama_cpp import LlamaCppVisionBackend
from app.services.vision.ollama import OllamaVisionBackend


class BackendRegistry:
    def __init__(self, backends):
        self.backends = backends

    def get(self, name):
        return self.backends[name]

    async def close(self):
        for backend in self.backends.values():
            await backend.close()


def create_backends(s: Settings):
    return BackendRegistry(
        {
            "ollama": OllamaVisionBackend(
                s.ollama_base_url,
                s.ollama_model,
                s.ollama_request_timeout,
                s.ollama_connect_timeout,
                s.ollama_keep_alive,
                s.ollama_max_concurrent_requests,
                s.ollama_max_retries,
            ),
            "llama_cpp": LlamaCppVisionBackend(
                s.llama_cpp_base_url,
                s.llama_cpp_model,
                s.page_processing_timeout,
                s.ollama_max_concurrent_requests,
                s.ollama_max_retries,
            ),
        }
    )


def create_backend(s):
    return create_backends(s).get(s.vision_backend)
