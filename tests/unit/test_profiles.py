from pathlib import Path

import pytest

from app.core.exceptions import ServiceError
from app.services.vision.profiles import ProfileRegistry


def test_profiles_loaded_and_unknown():
    registry = ProfileRegistry.load(Path("config/model_profiles"))
    profile = registry.get("default")
    assert profile.model == "document-ocr" and profile.user_prompt and profile.tile_overlap
    with pytest.raises(ServiceError) as error:
        registry.get("absent")
    assert error.value.code == "model_profile_not_found"


def test_public_profiles_hide_prompts():
    assert "system_prompt" not in ProfileRegistry.load(Path("config/model_profiles")).public()[0]
