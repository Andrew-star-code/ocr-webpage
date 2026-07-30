from pathlib import Path
import yaml
from pydantic import BaseModel,Field
class ModelProfile(BaseModel):
    name:str;backend:str;model:str;system_prompt:str;user_prompt:str
    recommended_resolution:int=Field(gt=0);max_image_size:int=Field(gt=0)
    tiling_strategy:str;num_ctx:int=Field(gt=0);num_predict:int=Field(gt=0)
    supports_json_schema:bool;coordinate_format:str;supports_tables:bool
    retry_mode:str;response_cleanup:str;two_stage:bool
def load_profiles(path:Path)->dict[str,ModelProfile]:
    profiles={}
    for file in path.glob("*.yaml"):
        profile=ModelProfile.model_validate(yaml.safe_load(file.read_text(encoding="utf-8")))
        profiles[profile.name]=profile
    if not profiles: raise ValueError(f"No model profiles found in {path}")
    return profiles
