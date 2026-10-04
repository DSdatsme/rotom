"""HTTP SERVER spans + Prometheus metrics endpoint."""

import json

import pytest
from fastapi.testclient import TestClient

from tests.conftest import span_rows

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(session_db, traced):
    from app.api.routes import create_app

    app = create_app(api_token=TOKEN)

    @app.post("/api/_test/boom")
    def boom():
        raise RuntimeError("db down")

    return TestClient(app)


def test_mutating_request_creates_server_span_with_route_template(client):
    from tests.test_api_routes import _seed

    _, draft_id = _seed()
    assert client.post(f"/api/drafts/{draft_id}/discard", headers=AUTH).status_code == 200
    (row,) = span_rows(span_kind="SERVER")
    assert row.name == "POST /api/drafts/{draft_id}/discard"
    attrs = json.loads(row.attributes)
    assert attrs["http.route"] == "/api/drafts/{draft_id}/discard"
    assert attrs["http.response.status_code"] == 200


def test_get_requests_are_not_traced(client):
    client.get("/api/health")
    client.get("/api/drafts", headers=AUTH)
    assert span_rows(span_kind="SERVER") == []


def test_server_error_marks_span_error(client):
    with pytest.raises(RuntimeError):
        client.post("/api/_test/boom")
    (row,) = span_rows(span_kind="SERVER")
    assert row.name == "POST /api/_test/boom"
    assert row.status == "ERROR"


def test_metrics_404_when_disabled(client):
    assert client.get("/metrics", headers=AUTH).status_code == 404


def test_metrics_requires_auth_and_exposes_series(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "metrics_enabled", True)
    assert client.get("/metrics").status_code == 401
    client.get("/api/health")
    body = client.get("/metrics", headers=AUTH).text
    assert "http_server_request_duration_seconds" in body
    assert 'route="/api/health"' in body


def test_metrics_span_processor_counts_runs_llm_and_tools():
    from opentelemetry.sdk.trace import TracerProvider

    from app.observability import semconv as sc
    from app.observability.metrics import REGISTRY, MetricsSpanProcessor

    def val(name, labels):
        return REGISTRY.get_sample_value(name, labels) or 0.0

    run_labels = {"kind": "mtest", "source": "scheduler", "status": "success"}
    tok_labels = {"provider": "gcp.gemini", "model": "m-test", "role": "draft", "token_type": "input"}
    tool_labels = {"tool": "t-test", "status": "ok"}
    before = (val("rotom_runs_total", run_labels), val("gen_ai_client_token_usage_total", tok_labels),
              val("rotom_tool_calls_total", tool_labels))

    provider = TracerProvider()
    provider.add_span_processor(MetricsSpanProcessor())
    tracer = provider.get_tracer("t")
    with tracer.start_as_current_span("mtest", attributes={
        sc.ROTOM_RUN_KIND: "mtest", sc.ROTOM_RUN_SOURCE: "scheduler", sc.ROTOM_RUN_STATUS: "success"}):
        with tracer.start_as_current_span("chat m-test", attributes={
            sc.OPERATION_NAME: sc.OP_CHAT, sc.PROVIDER_NAME: "gcp.gemini", sc.REQUEST_MODEL: "m-test",
            sc.ROTOM_LLM_ROLE: "draft", sc.USAGE_INPUT_TOKENS: 100, sc.USAGE_OUTPUT_TOKENS: 5,
            sc.ROTOM_COST_USD: 0.01}):
            pass
        with tracer.start_as_current_span("execute_tool t-test", attributes={
            sc.OPERATION_NAME: sc.OP_EXECUTE_TOOL, sc.TOOL_NAME: "t-test"}):
            pass

    assert val("rotom_runs_total", run_labels) == before[0] + 1
    assert val("gen_ai_client_token_usage_total", tok_labels) == before[1] + 100
    assert val("rotom_tool_calls_total", tool_labels) == before[2] + 1
