import json
import logging
from datetime import datetime, timezone

_ALLOWED = {
    "request_id",
    "job_id",
    "file_size",
    "mime_type",
    "page_count",
    "page_number",
    "image_width",
    "image_height",
    "model_profile",
    "backend",
    "model_name",
    "stage",
    "duration_ms",
    "retry_count",
    "status",
    "error_code",
    "storage_identifier",
}


class JsonFormatter(logging.Formatter):
    def format(self, record):
        value = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": "ocr",
        }
        value.update({key: getattr(record, key) for key in _ALLOWED if hasattr(record, key)})
        return json.dumps(value, ensure_ascii=False)


def configure_logging(level="INFO"):
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
