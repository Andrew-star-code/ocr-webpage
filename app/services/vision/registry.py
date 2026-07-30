from app.core.config import Settings
from app.services.vision.ollama import OllamaVisionBackend
from app.services.vision.llama_cpp import LlamaCppVisionBackend
def create_backend(s: Settings):
    if s.vision_backend=="ollama": return OllamaVisionBackend(s.ollama_base_url,s.ollama_model,s.ollama_request_timeout,s.ollama_connect_timeout,s.ollama_keep_alive,s.ollama_max_concurrent_requests)
    return LlamaCppVisionBackend(s.llama_cpp_base_url,s.llama_cpp_model,s.page_processing_timeout)
