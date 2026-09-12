import asyncio

import job


class FakeDB:
    instances = []

    def __init__(self):
        self.events = []
        self.updates = []
        FakeDB.instances.append(self)

    async def add_event(self, run_id, event_type, payload):
        self.events.append((run_id, event_type, payload))

    async def update(self, table, payload, **eq):
        self.updates.append((table, payload, eq))
        return []


def test_persist_fatal_marks_run_blocked_without_invalid_phase(monkeypatch):
    FakeDB.instances.clear()
    monkeypatch.setattr(job, "ResearchDB", FakeDB)

    try:
        raise ValueError("boom")
    except ValueError as exc:
        payload = asyncio.run(job._persist_fatal("run-1", exc))

    db = FakeDB.instances[0]
    assert payload["type"] == "ValueError"
    assert db.events[0][1] == "JOB_FATAL"
    update_payload = db.updates[0][1]
    assert update_payload["status"] == "BLOCKED"
    assert "phase" not in update_payload
    assert "updated_at" in update_payload
