import importlib.util
from pathlib import Path


def test_installed_application_package_and_runtime_profiles_are_available():
    assert importlib.util.find_spec("app") is not None
    assert importlib.util.find_spec("app.main") is not None
    assert Path("config/model_profiles/default.yaml").is_file()


def test_dockerfile_preserves_pep427_wheel_filename():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "COPY --from=builder /wheels/ /tmp/wheels/" in dockerfile
    assert "pip install --no-cache-dir /tmp/wheels/*.whl" in dockerfile
    assert "/tmp/package.whl" not in dockerfile
