from pathlib import Path
import yaml
from pydantic import BaseModel, Field, field_validator
from app.core.exceptions import ServiceError

class ModelProfile(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    backend: str
    model: str = Field(min_length=1, max_length=128)
    system_prompt: str
    user_prompt: str
    recommended_resolution: int = Field(ge=512, le=8192)
    max_image_size: int = Field(ge=262144, le=100_000_000)
    tiling_strategy: str
    tile_size: int = Field(default=1600, ge=512, le=4096)
    tile_overlap: int = Field(default=160, ge=32, le=1024)
    num_ctx: int = Field(ge=1024, le=262144)
    num_predict: int = Field(ge=128, le=65536)
    supports_json_schema: bool
    coordinate_format: str
    supports_tables: bool
    retry_mode: str
    response_cleanup: str
    two_stage: bool
    @field_validator("backend")
    @classmethod
    def valid_backend(cls, value):
        if value not in {"ollama", "llama_cpp"}: raise ValueError("unsupported backend")
        return value
    @field_validator("tiling_strategy")
    @classmethod
    def valid_tiling(cls, value):
        if value not in {"full_page", "tiles", "full_page_plus_tiles"}: raise ValueError("unsupported tiling strategy")
        return value
    @field_validator("coordinate_format")
    @classmethod
    def normalized_coordinates(cls, value):
        if value != "normalized": raise ValueError("only normalized coordinates are supported")
        return value

class ProfileRegistry:
    def __init__(self, profiles: dict[str, ModelProfile]): self._profiles = profiles
    @classmethod
    def load(cls, path: Path):
        profiles = {}
        for file in sorted(path.glob("*.yaml")):
            profile = ModelProfile.model_validate(yaml.safe_load(file.read_text(encoding="utf-8")))
            if profile.name in profiles: raise ValueError(f"Duplicate profile {profile.name}")
            profiles[profile.name] = profile
        if not profiles: raise ValueError(f"No model profiles found in {path}")
        return cls(profiles)
    def get(self, name: str) -> ModelProfile:
        try: return self._profiles[name]
        except KeyError as exc: raise ServiceError("model_profile_not_found", "Model profile not found", 404, {"profile": name}) from exc
    def public(self): return [p.model_dump(exclude={"system_prompt", "user_prompt"}) for p in self._profiles.values()]
    def names(self): return list(self._profiles)

def load_profiles(path: Path): return ProfileRegistry.load(path)
