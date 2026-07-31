from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = Field(8000, ge=1, le=65535)
    log_level: str = "INFO"
    api_keys: list[str] = Field(default_factory=lambda: ["change-me"])
    max_upload_size: int = Field(50 * 1024 * 1024, ge=1024, le=2_147_483_648)
    max_pages: int = Field(100, ge=1, le=10000)
    max_image_pixels: int = Field(50_000_000, ge=1_000_000)
    temp_dir: Path = Path("/tmp/ocr")
    result_dir: Path = Path("/tmp/ocr-results")
    result_ttl_seconds: int = Field(86400, ge=60)
    temp_file_ttl_seconds: int = Field(3600, ge=60)
    vision_backend: str = "ollama"
    default_model_profile: str = Field("default", min_length=1, max_length=64)
    profile_dir: Path = Path("config/model_profiles")
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "document-ocr"
    ollama_keep_alive: int = -1
    ollama_request_timeout: float = Field(600, gt=0)
    ollama_connect_timeout: float = Field(10, gt=0)
    ollama_max_retries: int = Field(2, ge=0, le=10)
    ollama_num_ctx: int = Field(32768, ge=1024)
    ollama_num_predict: int = Field(12000, ge=128)
    ollama_temperature: float = Field(0, ge=0, le=2)
    ollama_seed: int = 42
    ollama_max_concurrent_requests: int = Field(1, ge=1, le=16)
    llama_cpp_base_url: str = "http://llama-server:8080"
    llama_cpp_model: str = "document-ocr"
    redis_url: str = "redis://redis:6379/0"
    max_active_documents: int = Field(2, ge=1, le=64)
    max_parallel_pages: int = Field(1, ge=1, le=16)
    max_queue_size: int = Field(64, ge=1)
    queue_wait_timeout: int = Field(30, ge=1)
    page_processing_timeout: int = Field(600, ge=1)
    document_processing_timeout: int = Field(7200, ge=1)
    max_vision_retries: int = Field(2, ge=0, le=10)
    pdf_render_dpi: int = Field(300, ge=150, le=450)
    preprocess_mode: str = "auto"
    min_free_storage_bytes: int = Field(536870912, ge=0)
    rate_limit_per_minute: int = Field(30, ge=1)
    worker_heartbeat_ttl: int = Field(45, ge=10)
    readiness_cache_ttl: int = Field(30, ge=5)
    cleanup_interval_seconds: int = Field(300, ge=10)
    cleanup_lock_ttl_seconds: int = Field(600, ge=30)
    rate_limit_unauthenticated_per_minute: int = Field(10, ge=1)
    max_repair_response_chars: int = Field(100_000, ge=1_000, le=2_000_000)
    job_metadata_ttl_seconds: int = Field(86400, ge=60)
    worker_lock_ttl_seconds: int = Field(120, ge=30)
    worker_lock_renew_interval_seconds: int = Field(30, ge=5)

    @field_validator("api_keys", mode="before")
    @classmethod
    def split_keys(cls, v):
        return [x.strip() for x in v.split(",") if x.strip()] if isinstance(v, str) else v

    @field_validator("vision_backend")
    @classmethod
    def backend(cls, v):
        if v not in {"ollama", "llama_cpp"}:
            raise ValueError("VISION_BACKEND must be ollama or llama_cpp")
        return v

    @field_validator("preprocess_mode")
    @classmethod
    def mode(cls, v):
        if v not in {"none", "safe", "enhanced", "auto"}:
            raise ValueError("invalid PREPROCESS_MODE")
        return v

    @model_validator(mode="after")
    def production_secrets(self):
        if self.app_env == "production" and (not self.api_keys or "change-me" in self.api_keys):
            raise ValueError("Production API_KEYS must not contain change-me")
        if self.worker_lock_renew_interval_seconds >= self.worker_lock_ttl_seconds / 2:
            raise ValueError(
                "WORKER_LOCK_RENEW_INTERVAL_SECONDS must be less than half WORKER_LOCK_TTL_SECONDS"
            )
        return self


@lru_cache
def get_settings():
    return Settings()
