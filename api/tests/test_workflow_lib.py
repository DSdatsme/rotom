"""Tests for workflow helpers — no network, no keys, no inngest server."""

import asyncio

import pytest

from app.config import get_settings
from app.workflows import lib


def test_run_script_runs_python(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "SCRIPTS_DIR", tmp_path)
    (tmp_path / "hello.py").write_text("print('hi from script')")
    out = asyncio.run(lib.run_script("hello.py"))
    assert out.strip() == "hi from script"


def test_run_script_rejects_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "SCRIPTS_DIR", tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        asyncio.run(lib.run_script("../evil.py"))


def test_run_script_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "SCRIPTS_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        asyncio.run(lib.run_script("nope.py"))


def test_run_script_failure_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "SCRIPTS_DIR", tmp_path)
    (tmp_path / "boom.py").write_text("import sys; sys.exit(3)")
    with pytest.raises(RuntimeError, match="failed"):
        asyncio.run(lib.run_script("boom.py"))


def test_run_script_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "SCRIPTS_DIR", tmp_path)
    (tmp_path / "slow.py").write_text("import time; time.sleep(60)")
    with pytest.raises(RuntimeError, match="timed out"):
        asyncio.run(lib.run_script("slow.py", timeout=1))


class FakeModel:
    def invoke(self, prompt):
        class Msg:
            content = [{"type": "text", "text": "summary!"}]  # Gemini-style block list
        return Msg()


def test_llm_extracts_text(monkeypatch):
    monkeypatch.setattr(lib, "get_chat_model", lambda role, settings: FakeModel())
    monkeypatch.setattr(lib, "get_settings", lambda: None)
    assert asyncio.run(lib.llm("chat", "x")) == "summary!"


# ---- delivery + run recording ------------------------------------------------

class _FakeStep:
    async def run(self, step_id, handler, *args):
        return await handler(*args)


class _FakeCtx:
    def __init__(self, run_id="inngest-run-1", data=None):
        self.run_id = run_id
        self.step = _FakeStep()
        self.event = type("Event", (), {"data": data or {}})()


@pytest.fixture()
def sent(monkeypatch):
    messages: list[str] = []

    async def fake_notify(text):
        messages.append(text)

    monkeypatch.setattr(lib, "notify", fake_notify)
    monkeypatch.setattr(get_settings(), "telegram_enabled", True)
    return messages


def _runs(kind):
    from app.store.observability import RunLog, get_obs_session

    with get_obs_session() as s:
        return s.query(RunLog).filter(RunLog.kind == kind).order_by(RunLog.id).all()


async def test_notify_step_sends_without_recording_a_run(obs_db, sent):
    assert await lib.notify_step(_FakeCtx(), "morning_digest", "hi") == "sent"
    assert sent == ["hi"]
    assert _runs("morning_digest") == []  # the run was recorded by the earlier step


async def test_notify_step_with_telegram_off_records_a_degraded_run(obs_db, sent, monkeypatch):
    from app.store.observability import RunStatus

    monkeypatch.setattr(get_settings(), "telegram_enabled", False)
    assert await lib.notify_step(_FakeCtx("r-7"), "morning_digest", "hi") == "skipped: telegram off"
    assert sent == []
    (row,) = _runs("morning_digest")
    assert (row.status, row.external_id) == (RunStatus.DEGRADED, "r-7")


async def test_failed_send_is_logged_and_reraised(obs_db, monkeypatch, caplog):
    async def broken_notify(text):
        raise ConnectionError("telegram unreachable")

    monkeypatch.setattr(lib, "notify", broken_notify)
    monkeypatch.setattr(get_settings(), "telegram_enabled", True)
    with pytest.raises(ConnectionError):
        await lib.notify_step(_FakeCtx(), "morning_digest", "hi")
    assert "Digest delivery to Telegram failed" in caplog.text


async def test_record_failure_records_a_failed_run_under_the_failed_run_id(obs_db):
    from app.store.observability import RunStatus

    handler = lib.record_failure("morning_digest")
    await handler(_FakeCtx("failure-handler-run", data={
        "run_id": "r-9", "error": {"name": "Error", "message": "fetch-hn timed out"},
    }))
    (row,) = _runs("morning_digest")
    assert (row.status, row.external_id, row.source) == (RunStatus.FAILURE, "r-9", "inngest")
    assert "fetch-hn timed out" in row.error
