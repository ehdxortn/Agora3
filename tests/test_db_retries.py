import pytest

from research_engine import db as db_module
from research_engine.db import ResearchDB, _is_transient_db_error


def test_transient_classifier_recognizes_gateway_timeout():
    assert _is_transient_db_error(RuntimeError("APIError code 504 Gateway Timeout"))
    assert _is_transient_db_error(RuntimeError("Connection terminated due to connection timeout"))
    assert not _is_transient_db_error(RuntimeError("401 Invalid API key"))


@pytest.mark.asyncio
async def test_read_call_retries_transient_error(monkeypatch):
    instance = object.__new__(ResearchDB)
    calls = {"count": 0}

    def flaky():
        calls["count"] += 1
        if calls["count"] < 3:
            raise RuntimeError("504 Gateway Timeout")
        return ["ok"]

    async def no_sleep(_):
        return None

    monkeypatch.setattr(db_module.asyncio, "sleep", no_sleep)
    result = await instance._call(flaky, retry_transient=True)
    assert result == ["ok"]
    assert calls["count"] == 3


@pytest.mark.asyncio
async def test_non_transient_error_is_not_retried(monkeypatch):
    instance = object.__new__(ResearchDB)
    calls = {"count": 0}

    def bad_request():
        calls["count"] += 1
        raise RuntimeError("400 invalid request")

    async def no_sleep(_):
        return None

    monkeypatch.setattr(db_module.asyncio, "sleep", no_sleep)
    with pytest.raises(RuntimeError, match="400 invalid request"):
        await instance._call(bad_request, retry_transient=True)
    assert calls["count"] == 1
