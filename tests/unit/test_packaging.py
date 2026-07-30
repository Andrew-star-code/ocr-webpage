import importlib.util
from pathlib import Path


def test_installed_application_package_and_runtime_profiles_are_available():
    assert importlib.util.find_spec("app") is not None
    assert importlib.util.find_spec("app.main") is not None
    assert Path("config/model_profiles/default.yaml").is_file()
