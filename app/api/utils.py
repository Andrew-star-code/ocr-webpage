from urllib.parse import quote

from fastapi import UploadFile

from app.core.exceptions import ServiceError


async def read_upload(file: UploadFile, limit: int) -> bytes:
    chunks = []
    size = 0
    try:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise ServiceError("file_too_large", "Upload exceeds configured limit", 413)
            chunks.append(chunk)
    finally:
        await file.close()
    return b"".join(chunks)


def disposition(extension):
    return f"attachment; filename=\"result.{extension}\"; filename*=UTF-8''{quote('результат.' + extension)}"
