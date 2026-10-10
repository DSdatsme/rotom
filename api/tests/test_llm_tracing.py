"""LLM chat spans: usage, cost, content capture, errors; pricing; backfill; run metrics."""

import json
import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from tests.conftest import span_rows


def _result(content="ok", *, model="gemini-2.5-flash", inp=1000, out=200, cache=0, reasoning=0):
    msg = AIMessage(
        content=content,
        usage_metadata={
            "input_tokens": inp, "output_tokens": out, "total_tokens": inp + out,
            "input_token_details": {"cache_read": cache},
            "output_token_details": {"reasoning": reasoning},
        },
        response_metadata={"model_name": model, "finish_reason": "STOP"},
    )
    return LLMResult(generations=[[ChatGeneration(message=msg)]])


def test_cost_known_model():
    from app.observability.pricing import cost_usd

    c = cost_usd("gemini", "gemini-2.5-flash", input_tokens=1000, output_tokens=500)
    assert c is not None and c > 0


def test_cost_strips_models_prefix():
    from app.observability.pricing import cost_usd

    assert cost_usd("gemini", "models/gemini-2.5-flash", input_tokens=10, output_tokens=10) is not None


def test_cost_none_for_unknown_model():
    from app.observability.pricing import cost_usd

    assert cost_usd("gemini", "gemini-flash-latest", input_tokens=10, output_tokens=10) is None
    assert cost_usd("gemini", "", input_tokens=10, output_tokens=10) is None


def test_chat_span_records_usage_cost_and_content(traced):
    from app.observability.llm_tracing import LlmTracingCallback
    from app.observability.tracing import span

    cb = LlmTracingCallback("gemini", "gemini-flash-latest", "classify")
    rid = uuid.uuid4()
    with span("parent"):
        cb.on_chat_model_start({}, [[SystemMessage("sys"), HumanMessage("classify this")]], run_id=rid)
        cb.on_llm_end(_result("needs_reply", cache=400, reasoning=50), run_id=rid)
    (row,) = span_rows(operation="chat")
    (parent,) = span_rows(name="parent")
    assert row.name == "chat gemini-flash-latest"
    assert row.parent_span_id == parent.span_id
    assert row.span_kind == "CLIENT"
    assert row.provider == "gcp.gemini"
    assert row.model == "gemini-2.5-flash"  # resolved response model wins
    assert (row.input_tokens, row.output_tokens) == (1000, 200)
    assert (row.cache_read_tokens, row.reasoning_tokens) == (400, 50)
    assert row.cost_usd is not None and row.cost_usd > 0
    attrs = json.loads(row.attributes)
    assert attrs["rotom.llm.role"] == "classify"
    assert attrs["gen_ai.request.model"] == "gemini-flash-latest"
    assert list(attrs["gen_ai.response.finish_reasons"]) == ["STOP"]
    inp = json.loads(attrs["gen_ai.input.messages"])
    assert inp[1] == {"role": "user", "content": "classify this"}
    out = json.loads(attrs["gen_ai.output.messages"])
    assert out[0]["content"] == "needs_reply"


def test_llm_error_ends_span_as_error(traced):
    from app.observability.llm_tracing import LlmTracingCallback

    cb = LlmTracingCallback("gemini", "gemini-2.5-flash", "draft")
    rid = uuid.uuid4()
    cb.on_chat_model_start({}, [[HumanMessage("hi")]], run_id=rid)
    cb.on_llm_error(TimeoutError("read timed out"), run_id=rid)
    (row,) = span_rows(operation="chat")
    assert row.status == "ERROR"
    assert json.loads(row.attributes)["error.type"] == "TimeoutError"
    assert cb._spans == {}


def test_llm_span_truncates_large_and_block_content(traced, monkeypatch):
    from app.config import get_settings
    from app.observability.llm_tracing import LlmTracingCallback

    monkeypatch.setattr(get_settings(), "obs_content_max_chars", 100)
    cb = LlmTracingCallback("gemini", "gemini-2.5-flash", "chat")
    rid = uuid.uuid4()
    blocks = [{"type": "text", "text": "a" * 50_000}, {"type": "image_url", "image_url": "x"}]
    cb.on_chat_model_start({}, [[HumanMessage(content=blocks)]], run_id=rid)
    tool_msg = AIMessage(content="", tool_calls=[{"name": "list_emails", "args": {"limit": 5}, "id": "c1"}])
    cb.on_llm_end(LLMResult(generations=[[ChatGeneration(message=tool_msg)]]), run_id=rid)
    (row,) = span_rows(operation="chat")
    attrs = json.loads(row.attributes)
    inp = json.loads(attrs["gen_ai.input.messages"])
    assert len(inp[0]["content"]) < 200 and "…[+" in inp[0]["content"]
    out = json.loads(attrs["gen_ai.output.messages"])
    assert out[0]["tool_calls"] == [{"name": "list_emails", "args": {"limit": 5}}]


def test_unknown_model_still_records_tokens(traced):
    from app.observability.llm_tracing import LlmTracingCallback

    cb = LlmTracingCallback("groq", "brand-new-model", "classify")
    rid = uuid.uuid4()
    cb.on_llm_start({}, ["prompt"], run_id=rid)
    cb.on_llm_end(_result(model="brand-new-model", inp=10, out=5), run_id=rid)
    (row,) = span_rows(operation="chat")
    assert row.cost_usd is None
    assert row.input_tokens == 10


def test_callback_through_a_real_chat_model(traced):
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    from app.observability.llm_tracing import LlmTracingCallback

    msg = AIMessage(content="hello", usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5})
    model = GenericFakeChatModel(messages=iter([msg]), callbacks=[LlmTracingCallback("gemini", "fake", "chat")])
    assert model.invoke("hi").content == "hello"
    (row,) = span_rows(operation="chat")
    assert row.input_tokens == 3


def test_get_chat_model_attaches_tracing_callback():
    from app.config import Settings
    from app.llm.provider import get_chat_model
    from app.observability.llm_tracing import LlmTracingCallback

    model = get_chat_model("classify", Settings(model_provider="gemini", gemini_api_key="k"))
    assert any(isinstance(c, LlmTracingCallback) for c in model.callbacks)


def test_get_run_metrics_from_chat_spans(traced):
    from app.observability.llm_tracing import LlmTracingCallback
    from app.observability.sink import get_query_provider, record_run

    cb = LlmTracingCallback("gemini", "gemini-2.5-flash", "draft")
    with record_run("draft_generation") as run:
        for _ in range(2):
            rid = uuid.uuid4()
            cb.on_chat_model_start({}, [[HumanMessage("x")]], run_id=rid)
            cb.on_llm_end(_result(inp=100, out=10), run_id=rid)
    (m,) = get_query_provider().get_run(run.run_id)["metrics"]
    assert m["model"] == "gemini-2.5-flash"
    assert m["calls"] == 2
    assert m["input_tokens"] == 200
    assert m["cost_usd"] > 0


def test_backfill_copies_llm_usage_into_spans(obs_db):
    from datetime import datetime, timezone

    from sqlalchemy import text

    from app.store.observability import LLMUsage, _migrate, get_obs_session

    with get_obs_session() as s:
        s.add(LLMUsage(ts=datetime.now(timezone.utc), run_id=None, provider="gemini",
                       model="gemini-2.5-flash", role="classify", input_tokens=100,
                       output_tokens=20, latency_ms=900))
        s.commit()
    with obs_db._engine.begin() as conn:
        conn.execute(text("DELETE FROM obs_meta WHERE key = 'backfill.llm_usage.v1'"))
    _migrate(obs_db._engine)
    _migrate(obs_db._engine)  # idempotent
    rows = span_rows(operation="chat")
    assert len(rows) == 1
    row = rows[0]
    assert row.trace_id is None
    assert row.duration_ms == 900
    assert row.cost_usd is not None
    assert json.loads(row.attributes)["rotom.legacy"] is True


def test_set_content_failure_on_start_does_not_raise_or_leak(traced, monkeypatch):
    from app.observability import llm_tracing
    from app.observability.llm_tracing import LlmTracingCallback

    def boom(*a, **k):
        raise RuntimeError("redaction exploded")

    monkeypatch.setattr(llm_tracing, "set_content", boom)
    cb = LlmTracingCallback("gemini", "gemini-2.5-flash", "chat")
    rid = uuid.uuid4()
    cb.on_chat_model_start({}, [[HumanMessage("hi")]], run_id=rid)
    assert str(rid) in cb._spans
    cb.on_llm_end(_result(), run_id=rid)
    assert cb._spans == {}
    assert len(span_rows(operation="chat")) == 1


def test_error_finish_failure_does_not_raise_and_ends_span(traced, monkeypatch):
    from app.observability.llm_tracing import LlmTracingCallback

    cb = LlmTracingCallback("gemini", "gemini-2.5-flash", "draft")
    rid = uuid.uuid4()
    cb.on_chat_model_start({}, [[HumanMessage("hi")]], run_id=rid)

    def boom(*a, **k):
        raise RuntimeError("record_exception exploded")

    monkeypatch.setattr(cb._spans[str(rid)], "record_exception", boom)
    cb.on_llm_error(TimeoutError("x"), run_id=rid)
    assert cb._spans == {}
    assert len(span_rows(operation="chat")) == 1
