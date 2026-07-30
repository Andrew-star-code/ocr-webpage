import secrets
from fastapi import Header
from app.core.config import get_settings
from app.core.exceptions import ServiceError

async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    keys = get_settings().api_keys
    if not x_api_key or not any(secrets.compare_digest(x_api_key, key) for key in keys):
        raise ServiceError("invalid_request", "Invalid API key", 401)
