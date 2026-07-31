from types import SimpleNamespace

import pytest

from app.services.recognition.pipeline import ProcessingCancelled
from app.workers.tasks import _publish_result


class CancelledStore:
    async def complete(self, *args, **kwargs):
        return {"status": "cancelled"}


class Storage:
    def __init__(self):
        self.tagged = []
        self.deleted = []
        self.refs_deleted = []

    async def tag_job_file(self, job_id, stored):
        self.tagged.append((job_id, stored.identifier))

    async def delete_file(self, identifier):
        self.deleted.append(identifier)

    async def delete_reference(self, job_id, identifier):
        self.refs_deleted.append((job_id, identifier))


@pytest.mark.asyncio
async def test_cancel_winning_after_result_save_removes_file_and_reference():
    storage = Storage()
    stored = SimpleNamespace(identifier="result-orphan.json")
    with pytest.raises(ProcessingCancelled):
        await _publish_result(storage, CancelledStore(), "job", stored, "completed", 2)
    assert storage.tagged == [("job", "result-orphan.json")]
    assert storage.deleted == ["result-orphan.json"]
    assert storage.refs_deleted == [("job", "result-orphan.json")]
