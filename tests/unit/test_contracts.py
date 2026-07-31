import pytest

from app.core.config import Settings
from app.services.recognition.pipeline import normalize_raw_block_ids
from app.services.vision.base import ModelInfo
from app.workers.tasks import _publish_result


def test_expected_worker_helper_and_model_info_contract():
    assert callable(_publish_result)
    info = ModelInfo(name="model", present=True, vision_capable=False, structured_output=False)
    assert info.present and not info.vision_capable and not info.structured_output


def test_raw_block_ids_are_stable_and_preserve_duplicate_sources():
    payload = {"blocks": [{"id": "block-1"}, {"id": "block-1"}, {"id": ""}, {}]}
    normalized = normalize_raw_block_ids(payload, 2)
    assert normalized == normalize_raw_block_ids(payload, 2)
    assert [block["id"] for block in normalized["blocks"]] == [
        "page-2-raw-1",
        "page-2-raw-2",
        "page-2-raw-3",
        "page-2-raw-4",
    ]
    assert [block["source_id"] for block in normalized["blocks"]] == [
        "block-1",
        "block-1",
        None,
        None,
    ]


@pytest.mark.parametrize("key", ["change-me", "test-suite-key", "a" * 32, "abcdef" * 6])
def test_production_settings_reject_placeholder_keys(key):
    with pytest.raises(ValueError):
        Settings(app_env="production", api_keys=key)


def test_production_settings_accept_strong_key():
    settings = Settings(app_env="production", api_keys="s7W!m2Z@p9Q#v4N$x8K&c5J*e1R%u6T?")
    assert len(settings.api_keys) == 1
