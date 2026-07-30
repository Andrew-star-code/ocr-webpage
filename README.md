# Local Vision OCR

Production-oriented, fully local document recognition service for Russian and mixed Russian/English documents. Every rendered page is sent to the configured multimodal model; OpenCV only performs conservative image preparation and never supplies text.

## Architecture and data flow

`FastAPI → validation → per-page PyMuPDF/Pillow rendering → conservative OpenCV preprocessing → complexity/tiling utilities → VisionBackend → Pydantic/schema validation and retry → backend-neutral document → exporter`. `VisionBackend` isolates business logic from Ollama; `llama.cpp` is an explicitly selected alternative, never an automatic fallback. Ollama receives images through native `POST /api/chat` structured output. Pages are processed sequentially by default (`MAX_PARALLEL_PAGES=1`). Invalid, empty, truncated, explanatory, or schema-invalid responses are retried with exponential backoff; partial output requires explicit consent.

Asynchronous work uses Redis + Dramatiq: Dramatiq is substantially smaller than Celery while providing durable broker delivery and process workers. Redis stores bounded job state, encrypted-infrastructure-local input, result and TTL. Cancellation is cooperative. Queue and model concurrency remain deliberately conservative.

Tables remain structured objects through assembly. Table crops and overlapping tiles can be sent through the same mandatory Vision path; merging uses coordinates and exact-text deduplication. Searchable PDF preserves page raster and adds an invisible coordinate-derived text layer.

## Repository

```text
app/{api,core,schemas,services/{validation,rendering,preprocessing,tiling,vision,recognition,exporters,jobs},workers}
config/model_profiles/*.yaml  ollama/{Modelfile,README.md}
tests/{unit,integration}  Dockerfile  docker-compose*.yml
```

## Model preparation and launch

Requirements: Docker Compose, 16 GB RAM minimum; NVIDIA Container Toolkit for GPU. A 7B quantized vision model commonly needs about 8–12 GB VRAM, but image/context overhead varies. Never expose Redis or Ollama. The internal Docker network has no external route.

```bash
cp .env.example .env                 # replace API_KEYS
# temporarily use an admin invocation inside the internal service before API traffic
docker compose run --rm ollama pull qwen2.5vl:7b
docker compose run --rm -v ./ollama:/config ollama create document-ocr -f /config/Modelfile
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up --build
# or NVIDIA
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```

Model download/create is an operator action, never part of an OCR request. Profiles in `config/model_profiles` describe prompt compatibility, context, resolution, tiling, tables, coordinate format and one/two-stage mode. Add a YAML file without touching the pipeline. Set `VISION_BACKEND=llama_cpp` only when a separately operated OpenAI-compatible llama-server with vision projector is available; do not load the same model twice on one GPU.

## API

Swagger: `http://localhost:8000/docs`. Health is process-only at `/health`; `/ready` checks Redis, disk, backend, installed model, vision capability and structured-output metadata. Metrics are at `/metrics`. Readiness is intentionally false before the model is installed.

```bash
curl -X POST http://localhost:8000/v1/ocr -H 'X-API-Key: change-me' \
 -F file=@document.pdf -F output_format=docx -F language=rus+eng \
 -F model_profile=default -F preserve_layout=true -F detect_tables=true \
 -F preprocess_mode=auto --output result.docx
curl -X POST http://localhost:8000/v1/jobs -H 'X-API-Key: change-me' \
 -F file=@document.pdf -F output_format=json
curl -H 'X-API-Key: change-me' http://localhost:8000/v1/jobs/JOB_ID
curl -X POST -H 'X-API-Key: change-me' http://localhost:8000/v1/jobs/JOB_ID/cancel
```

```python
import httpx
with open("document.pdf", "rb") as f:
    response = httpx.post("http://localhost:8000/v1/ocr", headers={"X-API-Key":"change-me"}, files={"file":f}, data={"output_format":"json"}, timeout=7200)
response.raise_for_status()
print(response.json()["document_id"])
```

Supported input: PDF, PNG, JPEG, TIFF, WebP. Outputs: JSON, editable DOCX, TXT, Markdown and HTML (the exporter module also implements searchable PDF assembly). PDF DPI accepts 150–450; 300 is a strong default, 400–450 helps small print but sharply increases VRAM/time. Full-page recognition preserves global order; overlap tiling is useful only when pixels exceed the profile resolution.

## Security, operations, and diagnostics

Set long random comma-separated `API_KEYS`; comparisons are constant-time. Upload magic, PDF encryption/page counts, image pixels/frames and decompression bombs are checked. Containers run unprivileged/read-only with dropped capabilities. Text, base64, prompts and model output are never logged. Inputs expire after one hour and results after 24 hours by default. No cloud SDK exists in dependencies and runtime can operate without outgoing Internet after model preparation.

Tune one dimension at a time: VRAM failure → reduce model/context/DPI; truncation → increase `OLLAMA_NUM_PREDICT`; timeout → inspect `/metrics` and Ollama logs; queue rejection → add capacity only after measuring VRAM. `quality_score` is explicitly heuristic, not model probability.

## Development

```bash
python -m pip install -e '.[test]'
pytest -m 'not vlm_integration'
python -m compileall -q app
```

Real model tests require `RUN_VLM_INTEGRATION=1`, local fixtures containing no personal data, and an already-installed model. Prometheus metrics avoid user-controlled labels. JSON logs and request IDs support correlation without document contents.
