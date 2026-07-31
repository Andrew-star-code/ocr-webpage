from types import SimpleNamespace

import pytest

from app.services.jobs.state_machine import JobStateConflict
from app.services.recognition.pipeline import ProcessingCancelled
from app.workers.tasks import _publish_result


class CancelledStore:
    async def get(self, job_id):
        return {"status": "exporting"}

    async def complete(self, *args, **kwargs):
        return {"status": "cancelled"}


class StaticStore:
    def __init__(self, initial, completed=None):
        self.initial = initial
        self.completed = completed

    async def get(self, job_id):
        return self.initial

    async def complete(self, *args, **kwargs):
        return self.completed


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


@pytest.mark.asyncio
async def test_cancel_before_tag_removes_unpublished_result():
    storage = Storage()
    stored = SimpleNamespace(identifier="cancelled.json")
    with pytest.raises(ProcessingCancelled):
        await _publish_result(
            storage, StaticStore({"status": "cancelled"}), "job", stored, "completed", 1
        )
    assert storage.tagged == []
    assert storage.deleted == ["cancelled.json"]
    assert storage.refs_deleted == [("job", "cancelled.json")]


@pytest.mark.asyncio
async def test_successful_result_is_not_removed():
    storage = Storage()
    stored = SimpleNamespace(identifier="result.json")
    result = await _publish_result(
        storage,
        StaticStore({"status": "exporting"}, {"status": "completed"}),
        "job",
        stored,
        "completed",
        1,
    )
    assert result["status"] == "completed"
    assert storage.tagged == [("job", "result.json")]
    assert storage.deleted == []


@pytest.mark.asyncio
async def test_failed_terminal_state_rejects_publication():
    storage = Storage()
    stored = SimpleNamespace(identifier="failed.json")
    with pytest.raises(JobStateConflict):
        await _publish_result(
            storage, StaticStore({"status": "failed"}), "job", stored, "completed", 1
        )
    assert storage.deleted == ["failed.json"]


@pytest.mark.asyncio
async def test_repeated_publication_of_same_result_is_idempotent():
    storage = Storage()
    stored = SimpleNamespace(identifier="result.json")
    result = await _publish_result(
        storage,
        StaticStore({"status": "completed", "result_file": "result.json"}),
        "job",
        stored,
        "completed",
        1,
    )
    assert result["status"] == "completed"
    assert storage.tagged == []
    assert storage.deleted == []
