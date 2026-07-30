FROM python:3.12-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY pyproject.toml ./
COPY app ./app
RUN python -m pip install --no-cache-dir build && python -m build --wheel --outdir /wheels

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --create-home ocr \
    && mkdir -p /data/input /data/results /app/config/model_profiles \
    && chown -R ocr:ocr /data /app
COPY --from=builder /wheels/*.whl /tmp/
RUN python -m pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl
WORKDIR /app
COPY --chown=ocr:ocr config ./config
COPY --chown=ocr:ocr ollama ./ollama
USER ocr
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
