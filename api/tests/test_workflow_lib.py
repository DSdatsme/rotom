"""Tests for workflow helpers — no network, no keys, no inngest server."""

import asyncio

import pytest

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
