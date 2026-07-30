from functools import lru_cache
from pathlib import Path
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    api_keys: list[str] = Field(default_factory=lambda: ["change-me"])
    max_upload_size: int = 50 * 1024 * 1024
    max_pages: int = 100
    max_image_pixels: int = 50_000_000
    temp_dir: Path = Path("/tmp/ocr")
    result_dir: Path = Path("/tmp/ocr-results")
    result_ttl_seconds: int = 86400
    temp_file_ttl_seconds: int = 3600
    vision_backend: str = "ollama"
    default_model_profile: str = "default"
    profile_dir: Path = Path("config/model_profiles")
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "document-ocr"
    ollama_keep_alive: int = -1
    ollama_request_timeout: float = 600
    ollama_connect_timeout: float = 10
    ollama_max_retries: int = 2
    ollama_num_ctx: int = 32768
    ollama_num_predict: int = 12000
    ollama_temperature: float = 0
    ollama_seed: int = 42
    ollama_max_concurrent_requests: int = 1
    llama_cpp_base_url: str = "http://llama-server:8080"
    llama_cpp_model: str = "document-ocr"
    redis_url: str = "redis://redis:6379/0"
    max_active_documents: int = 2
    max_parallel_pages: int = 1
    max_queue_size: int = 64
    queue_wait_timeout: int = 30
    page_processing_timeout: int = 600
    document_processing_timeout: int = 7200
    max_vision_retries: int = 2
    pdf_render_dpi: int = 300
    preprocess_mode: str = "auto"
    min_free_storage_bytes: int = 536870912
    rate_limit_per_minute: int = 30

    @field_validator("api_keys", mode="before")
    @classmethod
    def split_keys(cls, value):
        return [x.strip() for x in value.split(",") if x.strip()] if isinstance(value, str) else value

    @field_validator("vision_backend")
    @classmethod
    def backend(cls, value):
        if value not in {"ollama", "llama_cpp"}: raise ValueError("VISION_BACKEND must be ollama or llama_cpp")
        return value

@lru_cache
def get_settings() -> Settings: return Settings()
