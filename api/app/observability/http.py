"""API request observability. Every request feeds HTTP metrics (when enabled); only
mutating requests become SERVER spans — the dashboard's GET polling would otherwise
drown the trace list. Spans are named by route template (low cardinality)."""

import logging
import time
from contextlib import nullcontext

from fastapi import FastAPI, Request
from opentelemetry.trace import SpanKind, Status, StatusCode

from app.observability import semconv as sc

logger = logging.getLogger(__name__)

TRACED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
UNMATCHED_ROUTE = "<unmatched>"
_UNOBSERVED_PATHS = frozenset({"/metrics"})


def _route_template(request: Request) -> str:
    # Raw paths of unmatched requests (scanners) must not become label/span-name values.
    route = request.scope.get("route")
    return getattr(route, "path", None) or UNMATCHED_ROUTE


def install_http_observability(app: FastAPI) -> None:
    @app.middleware("http")
    async def _observe(request: Request, call_next):
        from app.config import get_settings
        from app.observability.tracing import get_tracer

        if request.url.path in _UNOBSERVED_PATHS:
            return await call_next(request)
        method = request.method
        started = time.perf_counter()
        status_code = 500
        cm = (
            get_tracer().start_as_current_span(
                f"{method} {request.url.path}", kind=SpanKind.SERVER,
                attributes={sc.HTTP_METHOD: method, sc.URL_PATH: request.url.path},
            )
            if method in TRACED_METHODS else nullcontext()
        )
        with cm as server_span:
            try:
                response = await call_next(request)
                status_code = response.status_code
                return response
            finally:
                try:
                    route = _route_template(request)
                    if server_span is not None and server_span.is_recording():
                        server_span.update_name(f"{method} {route}")
                        server_span.set_attribute(sc.HTTP_ROUTE, route)
                        server_span.set_attribute(sc.HTTP_STATUS_CODE, status_code)
                        if status_code >= 500:
                            server_span.set_status(Status(StatusCode.ERROR))
                    if get_settings().metrics_enabled:
                        from app.observability.metrics import observe_http

                        observe_http(method, route, status_code, time.perf_counter() - started)
                except Exception:  # observability must never break the request
                    logger.debug("http observability failed", exc_info=True)
