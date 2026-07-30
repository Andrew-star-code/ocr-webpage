import pytest

from app.core.exceptions import ServiceError
from app.services.recognition.pipeline import extract_json


def test_array_is_rejected_by_recognition_contract():
    with pytest.raises(ServiceError) as error:
        extract_json("[]")
    assert error.value.code == "invalid_model_response"


def test_markdown_wrapper_and_extra_text():
    assert extract_json('```json\n{"blocks":[]}\n```')["blocks"] == []
    with pytest.raises(ServiceError) as error:
        extract_json('{"blocks":[]} explanation')
    assert error.value.code == "invalid_model_response"


def test_truncated_json_has_specific_code():
    with pytest.raises(ServiceError) as error:
        extract_json('{"blocks":[')
    assert error.value.code == "output_truncated"
