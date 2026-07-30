FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 fonts-dejavu-core && rm -rf /var/lib/apt/lists/* && useradd -r -u 10001 ocr
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
RUN mkdir -p /data/input /data/results && chown -R ocr:ocr /data
COPY --chown=ocr:ocr . .
USER ocr
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
