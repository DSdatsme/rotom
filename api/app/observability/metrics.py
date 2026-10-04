"""Prometheus metrics (opt-in: METRICS_ENABLED) on a private registry → GET /metrics.

Run/LLM/tool metrics are *derived from finished spans* (MetricsSpanProcessor), so spans
stay the single source of truth; HTTP metrics come from the middleware (it sees every
request, including the untraced GETs); log counts from LogCountHandler.
Names mirror OTel semconv where one exists (gen_ai.client.*, http.server.*).
"""

import logging

from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor
from opentelemetry.trace import StatusCode
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest

from app.observability import semconv as sc

logger = logging.getLogger(__name__)

REGISTRY = CollectorRegistry()

RUNS = Counter("rotom_runs", "Finished runs", ["kind", "source", "status"], registry=REGISTRY)
RUN_DURATION = Histogram(
    "rotom_run_duration_seconds", "Run wall time", ["kind"],
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1800), registry=REGISTRY,
)
LLM_DURATION = Histogram(
    "gen_ai_client_operation_duration_seconds", "LLM call latency",
    ["provider", "model", "role", "status"],
    buckets=(0.25, 0.5, 1, 2, 4, 8, 15, 30, 60, 120), registry=REGISTRY,
)
LLM_TOKENS = Counter(
    "gen_ai_client_token_usage", "LLM tokens", ["provider", "model", "role", "token_type"], registry=REGISTRY,
)
LLM_COST = Counter("rotom_llm_cost_usd", "LLM spend (USD)", ["provider", "model", "role"], registry=REGISTRY)
TOOL_CALLS = Counter("rotom_tool_calls", "Agent tool calls", ["tool", "status"], registry=REGISTRY)
HTTP_DURATION = Histogram(
    "http_server_request_duration_seconds", "API request latency",
    ["method", "route", "status_code"],
    buckets=(0.005, 0.025, 0.1, 0.25, 0.5, 1, 2.5, 5, 10), registry=REGISTRY,
)
LOG_RECORDS = Counter("rotom_log_records", "Log records by level", ["level"], registry=REGISTRY)

_TOKEN_ATTRS = (
    ("input", sc.USAGE_INPUT_TOKENS),
    ("output", sc.USAGE_OUTPUT_TOKENS),
    ("cache_read", sc.USAGE_CACHE_READ_INPUT_TOKENS),
    ("reasoning", sc.USAGE_REASONING_OUTPUT_TOKENS),
)


class MetricsSpanProcessor(SpanProcessor):
    def on_end(self, span: ReadableSpan) -> None:
        try:
            attrs = span.attributes or {}
            seconds = ((span.end_time or 0) - (span.start_time or 0)) / 1e9
            status = "error" if span.status.status_code == StatusCode.ERROR else "ok"
            op = attrs.get(sc.OPERATION_NAME)
            if sc.ROTOM_RUN_KIND in attrs:
                kind = str(attrs[sc.ROTOM_RUN_KIND])
                RUNS.labels(kind, str(attrs.get(sc.ROTOM_RUN_SOURCE, "")),
                            str(attrs.get(sc.ROTOM_RUN_STATUS, status))).inc()
                RUN_DURATION.labels(kind).observe(seconds)
            elif op == sc.OP_CHAT:
                provider = str(attrs.get(sc.PROVIDER_NAME, ""))
                model = str(attrs.get(sc.RESPONSE_MODEL) or attrs.get(sc.REQUEST_MODEL, ""))
                role = str(attrs.get(sc.ROTOM_LLM_ROLE, ""))
                LLM_DURATION.labels(provider, model, role, status).observe(seconds)
                for token_type, key in _TOKEN_ATTRS:
                    n = attrs.get(key)
                    if n:
                        LLM_TOKENS.labels(provider, model, role, token_type).inc(float(n))
                cost = attrs.get(sc.ROTOM_COST_USD)
                if cost:
                    LLM_COST.labels(provider, model, role).inc(float(cost))
            elif op == sc.OP_EXECUTE_TOOL:
                TOOL_CALLS.labels(str(attrs.get(sc.TOOL_NAME, "")), status).inc()
        except Exception:  # pragma: no cover - defensive
            logger.debug("metrics span processor failed", exc_info=True)


class LogCountHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        LOG_RECORDS.labels(record.levelname).inc()


def observe_http(method: str, route: str, status_code: int, seconds: float) -> None:
    HTTP_DURATION.labels(method, route, str(status_code)).observe(seconds)


def render() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
