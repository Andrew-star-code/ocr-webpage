# Local Vision OCR

Локальный сервис распознавания русских и смешанных документов. Каждая страница рендерится отдельно и обязательно проходит через выбранную Vision-модель; OpenCV используется только для консервативной подготовки изображения.

## Архитектура

```text
FastAPI → magic/MIME validation → LocalDocumentStorage
        → PyMuPDF/Pillow page rendering → OpenCV preprocessing
        → model profile → Ollama or llama.cpp → schema/Pydantic validation
        → full-page / overlapping tiles / table crops → document model
        → JSON / DOCX / TXT / Markdown / HTML / searchable PDF
Redis  → только job state, progress, heartbeat и непрозрачные file identifiers
Dramatiq worker → файлы общего volume → pipeline → atomic result write
```

YAML-профиль реально определяет backend, модель, prompts, structured output, контекст, выходной лимит, размер изображения, tile strategy/overlap, таблицы, cleanup/retry и двухэтапный флаг. Неизвестный профиль отклоняется. Ollama и llama.cpp не являются fallback друг для друга.

Redis + Dramatiq выбран как компактная надёжная очередь без значительной сложности Celery. Документы и результаты находятся только в `TEMP_DIR`/`RESULT_DIR`: случайные имена, atomic rename, TTL и удаление вместе с job. Worker публикует независимый heartbeat. `/ready` проверяет Redis, свежий worker, storage/disk, модель, Vision capability и кэшируемый реальный structured Vision inference.

## Подготовка модели

Runtime Ollama находится только в `internal: true` сети. Для первичной загрузки используется отдельный одноразовый Compose profile с исходящим доступом и тем же model volume:

```bash
cp .env.example .env
# обязательно замените API_KEYS; production не запустится с change-me
docker compose --profile model-init run --rm model-init
```

Затем model-init больше не запускается:

```bash
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up --build
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```

Offline-вариант: импортируйте заранее подготовленный Ollama volume на изолированном хосте и выполните `ollama create document-ocr -f /config/Modelfile`. API никогда не скачивает веса. Не запускайте одну модель одновременно в Ollama и llama.cpp на одном GPU.

## API

Swagger: `http://localhost:8000/docs`.

```bash
curl -X POST http://localhost:8000/v1/ocr -H 'X-API-Key: replace-me' \
 -F file=@document.pdf -F output_format=docx -F model_profile=default \
 -F language=rus+eng -F detect_tables=true -F preprocess_mode=auto \
 --output result.docx
curl -X POST http://localhost:8000/v1/jobs -H 'X-API-Key: replace-me' \
 -F file=@document.pdf -F output_format=json
curl -H 'X-API-Key: replace-me' http://localhost:8000/v1/jobs/JOB_ID
curl -H 'X-API-Key: replace-me' http://localhost:8000/v1/jobs/JOB_ID/result --output result.json
curl -X POST -H 'X-API-Key: replace-me' http://localhost:8000/v1/jobs/JOB_ID/cancel
```

`include_bounding_boxes=false` удаляет bbox из JSON, `include_processing_metadata=false` удаляет технические metadata, `preserve_layout=false` отключает стилевое восстановление DOCX. Ответ-файл использует безопасный ASCII filename и RFC 5987 UTF-8 filename. Upload читается ограниченными chunks.

Служебные endpoints: `/health`, `/ready`, `/metrics`, `/v1/formats`, `/v1/model`, `/v1/model/profiles`, `/v1/config/public`. Profiles endpoint возвращает загруженные YAML без prompts.

## Качество и производительность

Безопасный старт: одна страница и один Ollama request. DPI 300 подходит большинству документов; 400–450 помогает мелкому тексту, но резко увеличивает VRAM. При превышении profile resolution/pixels включаются overlapping tiles; координаты переводятся на страницу, а дубли удаляются только при совпадении типа, текста и пространственного overlap. Сложные/предупреждённые таблицы повторно распознаются по crop. `quality_score` — эвристика, не OCR-вероятность.

## Конфиденциальность

Нет облачных SDK и внешних OCR. Текст, Base64, prompts и полные ответы не логируются. API-key сравнивается безопасно, действует rate limit, magic/page/pixel/decompression ограничения. Контейнеры работают непривилегированно, read-only и без Linux capabilities; Redis/Ollama не публикуют порты. Входы и результаты имеют отдельные TTL.

## Проверки

```bash
python -m pip install -e '.[test]'
python -m compileall -q app
pytest -m "not vlm_integration"
docker compose config
docker compose -f docker-compose.yml -f docker-compose.cpu.yml config
docker compose -f docker-compose.yml -f docker-compose.gpu.yml config
```

Настоящий тест выполняет запрос с программно созданным изображением только при `RUN_VLM_INTEGRATION=1`. Для диагностики используйте `/ready`, `/metrics`, request ID и безопасные JSON logs.
