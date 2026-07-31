import asyncio
import os
import time
import uuid
from pathlib import Path

from app.core.exceptions import ServiceError
from app.services.storage.base import StoredFile


class LocalDocumentStorage:
    def __init__(self, temp_dir: Path, result_dir: Path, temp_ttl: int, result_ttl: int):
        self.temp_dir = temp_dir.resolve()
        self.result_dir = result_dir.resolve()
        self.temp_ttl = temp_ttl
        self.result_ttl = result_ttl
        self.temp_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.result_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _path(self, identifier):
        if not identifier or Path(identifier).name != identifier or ".." in identifier:
            raise ServiceError("invalid_request", "Invalid storage identifier")
        root = self.temp_dir if identifier.startswith("input-") else self.result_dir
        path = (root / identifier).resolve()
        if root not in path.parents:
            raise ServiceError("invalid_request", "Unsafe storage identifier")
        return path

    async def _atomic(self, path, data):
        def write():
            tmp = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
            with open(tmp, "xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)

        await asyncio.to_thread(write)

    async def save_input(self, job_id, data, mime_type):
        identifier = f"input-{uuid.uuid4().hex}.bin"
        await self._atomic(self._path(identifier), data)
        return StoredFile(identifier, mime_type, "bin", len(data))

    async def read_input(self, identifier):
        try:
            return await asyncio.to_thread(self._path(identifier).read_bytes)
        except FileNotFoundError as exc:
            raise ServiceError("result_expired", "Input expired", 410) from exc

    async def save_result(self, job_id, data, mime_type, extension):
        ext = extension.lstrip(".")
        if not ext.isalnum():
            raise ServiceError("invalid_request", "Invalid result extension")
        identifier = f"result-{uuid.uuid4().hex}.{ext}"
        await self._atomic(self._path(identifier), data)
        return StoredFile(identifier, mime_type, ext, len(data))

    async def read_result(self, identifier):
        try:
            return await asyncio.to_thread(self._path(identifier).read_bytes)
        except FileNotFoundError as exc:
            raise ServiceError("result_expired", "Result expired", 410) from exc

    async def delete_file(self, identifier):
        await asyncio.to_thread(self._path(identifier).unlink, missing_ok=True)

    async def delete_job_files(self, job_id):
        # Identifiers are looked up from job metadata; this method removes files tagged in sidecar names only.
        for root in (self.temp_dir, self.result_dir):
            for path in root.glob(f"*.{job_id}.ref"):
                try:
                    self._path(path.read_text()).unlink(missing_ok=True)
                    path.unlink(missing_ok=True)
                except (OSError, ServiceError):
                    path.unlink(missing_ok=True)

    async def tag_job_file(self, job_id, stored):
        root = self.temp_dir if stored.identifier.startswith("input-") else self.result_dir
        await self._atomic(root / f"{uuid.uuid4().hex}.{job_id}.ref", stored.identifier.encode())

    async def delete_reference(self, job_id, identifier):
        for root in (self.temp_dir, self.result_dir):
            for path in root.glob(f"*.{job_id}.ref"):
                try:
                    if path.read_text() == identifier:
                        path.unlink(missing_ok=True)
                except OSError:
                    continue

    async def exists(self, identifier):
        return await asyncio.to_thread(self._path(identifier).is_file)

    async def cleanup_expired(self, active_identifiers=None):
        active = set(active_identifiers or ())
        now = time.time()
        count = 0
        for root, ttl in ((self.temp_dir, self.temp_ttl), (self.result_dir, self.result_ttl)):
            for path in root.iterdir():
                if not path.is_file():
                    continue
                age = now - path.stat().st_mtime
                if path.name in active:
                    continue
                if path.name.endswith(".ref"):
                    try:
                        target = path.read_text()
                    except OSError:
                        target = ""
                    if target in active:
                        continue
                    if age > ttl or not target or not self._path(target).exists():
                        path.unlink(missing_ok=True)
                        count += 1
                elif path.name.endswith(".tmp"):
                    if age > max(60, ttl):
                        path.unlink(missing_ok=True)
                        count += 1
                elif age > ttl:
                    path.unlink(missing_ok=True)
                    count += 1
        return count

    async def healthcheck(self):
        try:
            probe = self.temp_dir / (".probe-" + uuid.uuid4().hex)
            await self._atomic(probe, b"")
            probe.unlink()
            return True
        except OSError:
            return False
