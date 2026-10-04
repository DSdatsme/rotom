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
    llm_labels = {"provider": "gcp.gemini", "model": "m-test", "role": "draft", "status": "ok"}
    cost_labels = {"provider": "gcp.gemini", "model": "m-test", "role": "draft"}
    before = (val("rotom_runs_total", run_labels), val("gen_ai_client_token_usage_total", tok_labels),
              val("rotom_tool_calls_total", tool_labels),
              val("gen_ai_client_operation_duration_seconds_count", llm_labels),
              val("rotom_llm_cost_usd_total", cost_labels))

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
    assert val("gen_ai_client_operation_duration_seconds_count", llm_labels) == before[3] + 1
    assert val("rotom_llm_cost_usd_total", cost_labels) == pytest.approx(before[4] + 0.01)


def test_unmatched_path_uses_constant_route(client):
    assert client.post("/wp-admin/x123").status_code == 404
    (row,) = span_rows(span_kind="SERVER")
    assert row.name == "POST <unmatched>"
    attrs = json.loads(row.attributes)
    assert attrs["http.route"] == "<unmatched>"
    assert attrs["url.path"] == "/wp-admin/x123"


def test_unmatched_paths_do_not_create_metric_labels(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "metrics_enabled", True)
    client.get("/wp-admin/aaa111")
    client.get("/phpmyadmin/bbb222")
    body = client.get("/metrics", headers=AUTH).text
    assert 'route="<unmatched>"' in body
    assert "aaa111" not in body and "bbb222" not in body


def _runs_total(kind):
    from app.observability.metrics import REGISTRY

    return sum(
        s.value for m in REGISTRY.collect() if m.name == "rotom_runs" for s in m.samples
        if s.name == "rotom_runs_total" and s.labels["kind"] == kind
    )


@pytest.mark.parametrize("enabled,expected", [(True, 1), (False, 0)])
def test_init_tracing_registers_metrics_processor_only_when_enabled(obs_db, monkeypatch, enabled, expected):
    from app.config import get_settings
    from app.observability import tracing
    from app.observability.sink import record_run

    monkeypatch.setattr(get_settings(), "metrics_enabled", enabled)
    tracing.shutdown_tracing()
    tracing.init_tracing(simple=True)
    try:
        before = _runs_total("wiretest")
        with record_run("wiretest"):
            pass
        assert _runs_total("wiretest") == before + expected
    finally:
        tracing.shutdown_tracing()


def test_setup_logging_adds_log_count_handler_when_enabled(obs_db, monkeypatch):
    import logging

    from app import logging_setup
    from app.config import get_settings
    from app.observability.metrics import REGISTRY, LogCountHandler

    monkeypatch.setattr(get_settings(), "metrics_enabled", True)
    root = logging.getLogger()
    saved = (root.handlers[:], root.level)
    try:
        logging_setup.setup_logging()
        assert any(isinstance(h, LogCountHandler) for h in root.handlers)
        labels = {"level": "ERROR"}
        before = REGISTRY.get_sample_value("rotom_log_records_total", labels) or 0.0
        logging.getLogger("app.wiretest").error("boom")
        assert REGISTRY.get_sample_value("rotom_log_records_total", labels) == before + 1
    finally:
        for h in root.handlers[:]:
            root.removeHandler(h)
            h.close()
        root.handlers[:] = saved[0]
        root.setLevel(saved[1])
        logging_setup._db_log_handler = None
