# Observability v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** End-to-end, SQL-queryable observability for rotom — one central log schema, OTel traces (runs → steps → agent/tools → LLM calls → logs) stored in `observability.db`, LLM cost, opt-in Prometheus `/metrics`, and real dashboards (Overview, Traces + waterfall, LLM, Logs).

**Architecture:** The OpenTelemetry SDK provides trace/span ids and context propagation; a custom `SqliteSpanExporter` writes finished spans to a `span` table (GenAI-semconv names promoted to columns). `record_run`, a LangChain callback, a tool wrapper, pipeline step spans and an HTTP middleware emit spans. Every log line is built by one module (`log_schema.py`), redacted, and stamped with trace/run ids. SQL views are the query surface; FastAPI read endpoints feed new Next.js pages.

**Tech Stack:** Python 3.12 (uv), FastAPI, SQLAlchemy 2 / SQLite, opentelemetry-api/sdk 1.45, genai-prices, prometheus-client, LangChain 1.x; Next.js 16 + React 19 + Base UI + Tailwind 4 + recharts 3.

**Spec:** `docs/superpowers/specs/2026-10-04-observability-v2-design.md`

## Global Constraints

- Branch `feature/observability-v2`; one commit per task; **no `Co-Authored-By` / AI attribution lines in commits** (owner's global rule).
- Tests never touch the network or a real LLM. Run backend tests with `cd api && uv run pytest -q`.
- Observability must never break observed work: every exporter/processor/callback/middleware/redaction path catches and degrades (stdout warning), never raises into the caller.
- All persistent telemetry lives in `./data/observability.db`. All timestamps stored UTC in SQLAlchemy's `YYYY-MM-DD HH:MM:SS.ffffff` format; the API emits ISO-8601 with `+00:00`.
- GenAI/OTel attribute names are spelled **only** in `api/app/observability/semconv.py`. The log line format is defined **only** in `api/app/observability/log_schema.py`.
- One asyncio process: new FastAPI observability read routes are **sync `def`** (threadpool), never `async def` doing SQLite I/O.
- Dependency floors: `opentelemetry-api>=1.45`, `opentelemetry-sdk>=1.45`, `genai-prices>=0.1.9`, `prometheus-client>=0.26`.
- Web: Next.js 16 App Router, Base UI (not Radix), bearer token stays server-side (`lib/api.ts` is `server-only`); `cd web && npm run lint && npm run build` must pass; read `web/AGENTS.md` before touching web code. Load the `dataviz` skill before writing chart code and `frontend-design` before page layout.
- Content capture defaults: `OBS_CAPTURE_CONTENT=true`, `OBS_CONTENT_MAX_CHARS=8000`. Retention: `LOG_RETENTION_DAYS=14`, `TRACE_RETENTION_DAYS=30`. Metrics: `METRICS_ENABLED=false`.

## Review Focus

1. **Spans arrive before their root** (a run still running, or an export batch split) → trace detail must still render, treating orphans as roots; the Traces list simply omits traces with no root yet. Pinned in Task 6 (`test_trace_detail_with_orphan_spans`) and Task 8 (`buildWaterfall` orphan handling).
2. **Huge or non-string LLM content** (content-block lists, tool calls, 50k-char emails) → truncated per message, valid JSON, no crash. Pinned in Task 3 (`test_llm_span_truncates_large_and_block_content`).
3. **LLM call raises** (timeout/429) → span ends with ERROR + `error.type`, nothing leaks in the callback's in-flight map. Pinned in Task 3 (`test_llm_error_ends_span_as_error`).
4. **Unknown/alias model for pricing** (`gemini-flash-latest`, `models/…`, new Groq model) → `cost_usd` NULL, tokens still recorded, no exception. Pinned in Task 3 (`test_cost_none_for_unknown_model`, `test_cost_strips_models_prefix`).
5. **Secrets in tracebacks and `extra=` fields** (httpx errors at WARNING include the token URL) → redacted on stdout and in DB. Pinned in Task 1 (`test_redacts_exc_info_and_extras`).

---

## File Structure

**Backend — create**
- `api/app/observability/redact.py` — secret masking (values + token-shape regexes).
- `api/app/observability/log_schema.py` — THE log format: `ContextFilter`, `to_event`, `render`, `JsonFormatter`.
- `api/app/observability/semconv.py` — every OTel/GenAI attribute name + provider maps.
- `api/app/observability/tracing.py` — TracerProvider lifecycle, `get_tracer`, `span()`, `set_content`, `trace_id_of`.
- `api/app/observability/span_exporter.py` — `SqliteSpanExporter`, `span_to_row`.
- `api/app/observability/pricing.py` — `cost_usd()` via genai-prices.
- `api/app/observability/llm_tracing.py` — `LlmTracingCallback` (replaces `UsageCallback`).
- `api/app/observability/metrics.py` — Prometheus registry, `MetricsSpanProcessor`, `LogCountHandler`, `observe_http`, `render`.
- `api/app/observability/http.py` — `install_http_observability(app)` middleware.
- `api/app/observability/queries.py` — dashboard read models (overview, traces, trace detail, llm stats).
- Tests: `api/tests/test_log_schema.py`, `test_tracing.py`, `test_llm_tracing.py`, `test_agent_tracing.py`, `test_metrics_http.py`, `test_obs_queries.py`.

**Backend — modify**
- `api/app/logging_setup.py` — wiring only (handlers, `NOISE_LEVELS`, `flush_db_logs`).
- `api/app/store/observability.py` — `Span`, `ObsMeta`, new columns, migrations, scrub, backfill, views, retention.
- `api/app/observability/{events,sink,sqlite_sink}.py` — run spans, trace ids, drop usage/log-blob paths.
- `api/app/llm/provider.py`, `api/app/agent/{graph,toolkit}.py`, `api/app/tools/gmail/pipeline.py` — instrumentation.
- `api/app/api/routes.py`, `api/app/main.py`, `api/app/scheduler/jobs.py`, `api/app/config.py`, `api/pyproject.toml`.
- `api/tests/conftest.py` (shared `obs_db` + `traced` fixtures), `test_observability.py`, `test_observability_logs.py`, `test_pipeline.py`, `test_provider.py`.

**Web — create**
- `web/lib/view/trace.ts` — waterfall layout + span helpers.
- `web/components/obs/{kpi,window-tabs,runs-chart,spend-chart,job-health,problems-list,traces-table,trace-view,messages}.tsx`.
- `web/app/observability/traces/page.tsx`, `web/app/observability/traces/[traceId]/page.tsx`, `web/app/observability/llm/page.tsx`.

**Web — modify / delete**
- `web/lib/api.ts`, `web/lib/nav.ts`, `web/lib/format/number.ts`, `web/app/observability/page.tsx`, `web/app/email/runs/[id]/page.tsx`, `web/components/run-detail-live.tsx`, `web/components/logs-panel.tsx`.
- Delete `web/components/tokens-chart.tsx`, `web/lib/view/usage.ts` (only consumer was the old usage page).

**Docs/ops** — `docs/observability/README.md`, new `docs/observability/QUERIES.md`, `AGENTS.md`, `TODO.md`, `.env.example`, `Makefile`.

---

### Task 1: Central log schema, redaction, noise policy, trace-ready log rows

**Files:**
- Create: `api/app/observability/redact.py`, `api/app/observability/log_schema.py`, `api/tests/test_log_schema.py`
- Modify: `api/app/logging_setup.py` (rewrite), `api/app/store/observability.py`, `api/app/observability/events.py`, `api/app/observability/sink.py`, `api/app/observability/sqlite_sink.py`, `api/app/api/routes.py` (logs endpoint param), `api/pyproject.toml`, `api/tests/conftest.py`, `api/tests/test_observability.py`, `api/tests/test_observability_logs.py`

**Interfaces:**
- Produces: `redact(text) -> text`, `redact_obj(value)`, `secret_values() -> tuple[str, ...]` (lru-cached; tests call `secret_values.cache_clear()`), `MASK = "[REDACTED]"`; `log_schema.CORE_FIELDS`, `ContextFilter`, `to_event(record) -> dict`, `render(event) -> str`, `JsonFormatter`; `logging_setup.NOISE_LEVELS`, `setup_logging()`, `flush_db_logs()`, `DbLogHandler`; `ObsMeta` model + `_meta_get(conn, key)`, `_meta_set(conn, key, value)`; `LogEntry.trace_id/span_id/exc_info`; `SqliteSink.list_logs(..., trace_id=None)`; `RunResult(status, summary="", error="")` (no `logs`); `get_run()["logs"]` = JSONL rendered from `log_entry` when the legacy blob is empty.
- Test fixtures (conftest): `obs_db` (fresh DB + `_migrate`).

- [ ] **Step 1: Add OTel deps**

Run: `cd api && uv add "opentelemetry-api>=1.45" "opentelemetry-sdk>=1.45"`
Expected: `pyproject.toml` + `uv.lock` updated.

- [ ] **Step 2: Move the `obs_db` fixture into conftest**

Append to `api/tests/conftest.py`:

```python
@pytest.fixture()
def obs_db(tmp_path):
    """Fresh observability DB (tables + migrations + views) per test."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.store import observability as obs

    engine = create_engine(f"sqlite:///{tmp_path / 'obs.db'}")
    obs.ObsBase.metadata.create_all(engine)
    obs._migrate(engine)
    obs._engine = engine
    obs._SessionFactory = sessionmaker(engine, expire_on_commit=False)
    yield obs
    obs._engine = None
    obs._SessionFactory = None
```

Delete the local `obs_db` fixtures (and their now-unused `create_engine`/`sessionmaker` imports) from `api/tests/test_observability.py` and `api/tests/test_observability_logs.py`.

- [ ] **Step 3: Write the failing tests** — create `api/tests/test_log_schema.py`:

```python
"""Central log schema: fields, redaction, context stamping, DB persistence."""

import json
import logging

import pytest

FAKE_BOT_TOKEN = "1234567890:AAAbbbCCCdddEEEfffGGGhhhIIIjjjKKKlll0"


def _record(msg="hello %s", args=("world",), level=logging.INFO, name="app.test", **extra):
    r = logging.LogRecord(name, level, "/x/app/test.py", 42, msg, args, None)
    for k, v in extra.items():
        setattr(r, k, v)
    return r


def test_to_event_has_ordered_core_fields():
    from app.observability.log_schema import CORE_FIELDS, to_event

    event = to_event(_record())
    assert tuple(event)[: len(CORE_FIELDS)] == CORE_FIELDS
    assert event["msg"] == "hello world"
    assert event["level"] == "INFO"
    assert event["filename"] == "test.py"
    assert event["lineno"] == 42


def test_extra_fields_follow_core_fields():
    from app.observability.log_schema import to_event

    event = to_event(_record(account="personal", count=3))
    assert event["account"] == "personal"
    assert event["count"] == 3


def test_redacts_telegram_token_in_httpx_style_message():
    from app.observability.log_schema import to_event

    msg = f'HTTP Request: POST https://api.telegram.org/bot{FAKE_BOT_TOKEN}/getUpdates "HTTP/1.1 200 OK"'
    event = to_event(_record(msg=msg, args=()))
    assert FAKE_BOT_TOKEN not in event["msg"]
    assert "[REDACTED]" in event["msg"]


def test_redacts_configured_secret_values(monkeypatch):
    from app.observability import redact as R
    from app.observability.log_schema import to_event

    monkeypatch.setenv("SOME_SERVICE_TOKEN", "plain-secret-value-123456")
    R.secret_values.cache_clear()
    try:
        event = to_event(_record(msg="using plain-secret-value-123456 now", args=()))
    finally:
        R.secret_values.cache_clear()
    assert "plain-secret-value-123456" not in event["msg"]


def test_redacts_exc_info_and_extras():
    from app.observability.log_schema import to_event

    try:
        raise RuntimeError(f"boom at https://api.telegram.org/bot{FAKE_BOT_TOKEN}/send")
    except RuntimeError:
        import sys
        rec = _record(msg="failed", args=(), url=f"https://x/bot{FAKE_BOT_TOKEN}/y")
        rec.exc_info = sys.exc_info()
    event = to_event(rec)
    assert FAKE_BOT_TOKEN not in event["exc_info"]
    assert "RuntimeError" in event["exc_info"]
    assert FAKE_BOT_TOKEN not in event["url"]


def test_redact_patterns_cover_common_token_shapes():
    from app.observability.redact import redact

    for secret in (
        "Bearer abcdefghijklmnop1234",
        "AIza" + "A" * 35,
        "sk-ant-" + "a" * 30,
        "gsk_" + "a" * 30,
        "ghp_" + "a" * 36,
    ):
        assert secret not in redact(f"x {secret} y")
    assert redact("nothing secret here 12:30:00") == "nothing secret here 12:30:00"


def test_render_drops_null_fields_and_is_json():
    from app.observability.log_schema import render, to_event

    line = render(to_event(_record()))
    parsed = json.loads(line)
    assert "trace_id" not in parsed  # no active span → dropped
    assert parsed["msg"] == "hello world"


def test_context_filter_stamps_trace_and_run_ids():
    from opentelemetry.sdk.trace import TracerProvider

    from app.observability.log_schema import ContextFilter, to_event
    from app.observability.sink import current_run_id

    tracer = TracerProvider().get_tracer("t")
    token = current_run_id.set("7")
    try:
        with tracer.start_as_current_span("x") as sp:
            rec = _record()
            ContextFilter().filter(rec)
            expected = format(sp.get_span_context().trace_id, "032x")
    finally:
        current_run_id.reset(token)
    event = to_event(rec)
    assert event["trace_id"] == expected
    assert len(event["span_id"]) == 16
    assert event["run_id"] == "7"


def test_db_handler_persists_trace_columns_exc_and_extra(obs_db):
    from opentelemetry.sdk.trace import TracerProvider

    from app.logging_setup import DbLogHandler
    from app.store.observability import LogEntry, get_obs_session

    handler = DbLogHandler()
    tracer = TracerProvider().get_tracer("t")
    with tracer.start_as_current_span("x"):
        try:
            raise ValueError("bad")
        except ValueError:
            import sys
            rec = _record(msg="oops", args=(), level=logging.ERROR, account="work")
            rec.exc_info = sys.exc_info()
            handler.handle(rec)  # handle() runs filters (ContextFilter) like a real logger
    handler._flush()
    with get_obs_session() as s:
        row = s.query(LogEntry).one()
    assert row.msg == "oops"
    assert row.trace_id and len(row.trace_id) == 32
    assert "ValueError" in row.exc_info
    extra = json.loads(row.extra)
    assert extra["account"] == "work"
    assert extra["lineno"] == 42
    handler.close()


def test_setup_logging_applies_noise_policy(obs_db):
    from app import logging_setup

    root = logging.getLogger()
    saved = (root.handlers[:], root.level)
    try:
        logging_setup.setup_logging()
        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("uvicorn.access").level == logging.WARNING
        assert any(isinstance(h, logging_setup.DbLogHandler) for h in root.handlers)
    finally:
        for h in root.handlers[:]:
            root.removeHandler(h)
            h.close()
        root.handlers[:] = saved[0]
        root.setLevel(saved[1])
        logging_setup._db_log_handler = None


def test_get_run_renders_logs_from_log_entry(obs_db):
    from datetime import datetime, timezone

    from app.observability.events import RunStart
    from app.observability.sqlite_sink import SqliteSink
    from app.store.observability import LogEntry, get_obs_session

    sink = SqliteSink()
    run_id = sink.start_run(RunStart(kind="k"))
    with get_obs_session() as s:
        s.add(LogEntry(ts=datetime.now(timezone.utc), level="INFO", logger="app.x",
                       msg="step one", run_id=int(run_id), extra='{"lineno": 3}'))
        s.add(LogEntry(ts=datetime.now(timezone.utc), level="ERROR", logger="app.x",
                       msg="step two", run_id=int(run_id), exc_info="Traceback: boom"))
        s.commit()
    lines = [json.loads(l) for l in sink.get_run(run_id)["logs"].splitlines()]
    assert [l["msg"] for l in lines] == ["step one", "step two"]
    assert lines[0]["lineno"] == 3
    assert lines[1]["exc_info"] == "Traceback: boom"


def test_scrub_migration_masks_existing_rows(obs_db, monkeypatch):
    from datetime import datetime, timezone

    from sqlalchemy import text

    from app.observability import redact as R
    from app.store.observability import LogEntry, _migrate, get_obs_session

    monkeypatch.setenv("LEAKY_BOT_TOKEN", FAKE_BOT_TOKEN)
    R.secret_values.cache_clear()
    try:
        with get_obs_session() as s:
            s.add(LogEntry(ts=datetime.now(timezone.utc), level="INFO", logger="httpx",
                           msg=f"GET https://api.telegram.org/bot{FAKE_BOT_TOKEN}/getMe"))
            s.commit()
        with obs_db._engine.begin() as conn:
            conn.execute(text("DELETE FROM obs_meta WHERE key = 'scrub.secrets.v1'"))
        _migrate(obs_db._engine)
        with get_obs_session() as s:
            assert FAKE_BOT_TOKEN not in s.query(LogEntry).one().msg
    finally:
        R.secret_values.cache_clear()


def test_list_logs_filters_by_trace_id(obs_db):
    from datetime import datetime, timezone

    from app.observability.sqlite_sink import SqliteSink
    from app.store.observability import LogEntry, get_obs_session

    with get_obs_session() as s:
        s.add(LogEntry(ts=datetime.now(timezone.utc), level="INFO", logger="t", msg="a", trace_id="a" * 32))
        s.add(LogEntry(ts=datetime.now(timezone.utc), level="INFO", logger="t", msg="b", trace_id="b" * 32))
        s.commit()
    res = SqliteSink().list_logs(trace_id="a" * 32)
    assert [r["msg"] for r in res["logs"]] == ["a"]
    assert res["logs"][0]["trace_id"] == "a" * 32
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_log_schema.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.observability.log_schema'`.

- [ ] **Step 5: Create `api/app/observability/redact.py`**

```python
"""Secret redaction for everything observability prints or persists.

Applied by the log schema (every log line: stdout + DB) and by span content capture
(prompts, responses, tool payloads). Two layers: the literal *values* of configured
secrets (exact, format-agnostic) and regex *shapes* of well-known token formats
(catches secrets we were never told about, e.g. a key pasted into an email)."""

import os
import re
from functools import lru_cache
from typing import Any

MASK = "[REDACTED]"

_SECRET_FIELDS = (
    "telegram_bot_token", "api_token", "gemini_api_key", "anthropic_api_key",
    "groq_api_key", "gmail_client_secret", "claude_code_oauth_token",
)
_SECRET_SUFFIXES = ("_TOKEN", "_SECRET", "_KEY", "_PASSWORD")
_MIN_SECRET_LEN = 12  # shorter values collide with ordinary text

_PATTERNS = (
    re.compile(r"(?<![0-9])\d{6,12}:[A-Za-z0-9_-]{30,}"),  # Telegram bot token (follows "bot")
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),   # Authorization: Bearer …
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}"),                 # Google API key
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"),             # Anthropic key / Claude OAuth token
    re.compile(r"\bgsk_[A-Za-z0-9]{20,}"),                  # Groq
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),            # GitHub tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}"),
    re.compile(r"\bya29\.[A-Za-z0-9_.-]{20,}"),             # Google OAuth access token
    re.compile(r"\b1//[A-Za-z0-9_-]{30,}"),                 # Google OAuth refresh token
)


@lru_cache(maxsize=1)
def secret_values() -> tuple[str, ...]:
    """Configured secret values, longest first (a secret containing another masks whole)."""
    values: set[str] = set()
    try:
        from app.config import get_settings

        settings = get_settings()
        values.update(str(getattr(settings, f, "") or "") for f in _SECRET_FIELDS)
        for key, value in (settings.model_extra or {}).items():
            if key.upper().endswith(_SECRET_SUFFIXES):
                values.add(str(value or ""))
    except Exception:  # settings unavailable — the env scan below still runs
        pass
    for key, value in os.environ.items():
        if key.upper().endswith(_SECRET_SUFFIXES):
            values.add(value)
    return tuple(sorted((v for v in values if len(v) >= _MIN_SECRET_LEN), key=len, reverse=True))


def redact(text: Any) -> Any:
    """Mask secrets in a string; non-strings pass through unchanged."""
    if not isinstance(text, str) or not text:
        return text
    for value in secret_values():
        if value in text:
            text = text.replace(value, MASK)
    for pattern in _PATTERNS:
        text = pattern.sub(MASK, text)
    return text


def redact_obj(value: Any) -> Any:
    """`redact` applied recursively through dicts, lists and tuples."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_obj(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_obj(v) for v in value]
    return value
```

- [ ] **Step 6: Create `api/app/observability/log_schema.py`**

```python
"""THE log format — the single source of truth for every log line rotom emits.

stdout (JSON lines) and the `log_entry` table (and through it the dashboard's Logs
explorer, run detail and trace view) all build records with `to_event()`. To add,
rename or drop a field, or change redaction, edit this file only.

Run/trace context is stamped onto the record by `ContextFilter` at emit time, in the
emitting thread, so handlers that buffer and write later (DbLogHandler) keep the right ids.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from opentelemetry import trace

from app.observability.redact import redact, redact_obj
from app.observability.sink import current_run_id, current_run_kind

# Ordered core fields; anything passed via `extra={...}` follows them.
CORE_FIELDS = (
    "ts", "level", "logger", "msg", "filename", "lineno",
    "run_id", "kind", "trace_id", "span_id", "exc_info",
)

# LogRecord internals that are never emitted as extra fields.
_RECORD_INTERNALS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
    "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs",
    "relativeCreated", "thread", "threadName", "processName", "process", "taskName",
    "message", "asctime", "color_message", "run_id", "kind", "trace_id", "span_id",
})

_exc_formatter = logging.Formatter()


class ContextFilter(logging.Filter):
    """Stamp run + trace context onto a record once, in the thread that emitted it."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "trace_id"):
            record.run_id = current_run_id.get()
            record.kind = current_run_kind.get()
            ctx = trace.get_current_span().get_span_context()
            record.trace_id = format(ctx.trace_id, "032x") if ctx.is_valid else None
            record.span_id = format(ctx.span_id, "016x") if ctx.is_valid else None
        return True


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return redact(str(value))


def to_event(record: logging.LogRecord) -> dict[str, Any]:
    """LogRecord → ordered, redacted, JSON-safe event dict."""
    exc = None
    if record.exc_info:
        exc = redact(_exc_formatter.formatException(record.exc_info))
    elif record.exc_text:
        exc = redact(record.exc_text)
    event: dict[str, Any] = {
        "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
        "level": record.levelname,
        "logger": record.name,
        "msg": redact(record.getMessage()),
        "filename": record.filename,
        "lineno": record.lineno,
        "run_id": getattr(record, "run_id", None),
        "kind": getattr(record, "kind", None),
        "trace_id": getattr(record, "trace_id", None),
        "span_id": getattr(record, "span_id", None),
        "exc_info": exc,
    }
    for key, value in record.__dict__.items():
        if key in _RECORD_INTERNALS or key.startswith("_") or key in event:
            continue
        event[key] = _json_safe(redact_obj(value))
    return event


def render(event: dict[str, Any]) -> str:
    """One JSON line; null fields are dropped to keep stdout readable."""
    return json.dumps({k: v for k, v in event.items() if v is not None}, default=str)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return render(to_event(record))
```

- [ ] **Step 7: Rewrite `api/app/logging_setup.py`**

```python
"""Logging wiring: handlers + noise policy.

The log *format* lives in app/observability/log_schema.py — edit that file to change
what a log line contains. This module only decides where lines go and which loggers
are too noisy to keep at INFO.
"""

import json
import logging
import threading
from datetime import datetime, timezone

from app.observability.log_schema import ContextFilter, JsonFormatter, to_event

# Third-party loggers capped at a level. httpx logs every request URL at INFO and
# Telegram's URLs embed the bot token; uvicorn.access and APScheduler job chatter are
# replaced by HTTP/run spans + metrics. sqlalchemy must stay ≥WARNING so its own INFO
# statements can't re-enter DbLogHandler.
NOISE_LEVELS: dict[str, int] = {
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "uvicorn.access": logging.WARNING,
    "apscheduler.executors.default": logging.WARNING,
    "apscheduler.scheduler": logging.WARNING,
    "sqlalchemy": logging.WARNING,
}

# Event keys stored in dedicated log_entry columns; every other key goes to `extra`.
_LOG_ENTRY_COLUMNS = ("level", "logger", "msg", "run_id", "kind", "trace_id", "span_id", "exc_info")

_DB_FLUSH_EVERY = 20          # flush after this many buffered records
_DB_FLUSH_INTERVAL_SEC = 5.0  # …and at least this often


def _as_int(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class DbLogHandler(logging.Handler):
    """Persist log records to `log_entry` (observability.db), buffered.

    Reentrancy-safe: ignores `sqlalchemy*` loggers and drops records emitted during
    its own flush. Never raises into the logging call.
    """

    _BLOCKED_PREFIXES = ("sqlalchemy",)

    def __init__(self):
        super().__init__()
        self.addFilter(ContextFilter())
        self._lock = threading.Lock()
        self._buffer: list = []
        self._writing = False
        self._timer: threading.Timer | None = None
        self._closed = False

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self._closed or (record.name or "").startswith(self._BLOCKED_PREFIXES):
                return
            with self._lock:
                if self._writing:
                    return  # re-entrancy from our own flush path — drop to avoid a storm
                self._buffer.append(record)
                should_flush = len(self._buffer) >= _DB_FLUSH_EVERY
            if should_flush:
                self._flush()
            elif self._timer is None:
                self._arm_timer()
        except Exception:
            self.handleError(record)

    def _arm_timer(self):
        with self._lock:
            if self._timer is None and not self._closed:
                t = threading.Timer(_DB_FLUSH_INTERVAL_SEC, self._flush)
                t.daemon = True
                t.start()
                self._timer = t

    def _flush(self):
        with self._lock:
            if self._writing:
                return
            if not self._buffer:
                self._timer = None
                return
            records, self._buffer = self._buffer, []
            self._writing = True
            self._timer = None
        try:
            self._persist(records)
        except Exception:
            pass  # never let a flush kill the app
        finally:
            with self._lock:
                self._writing = False

    def _persist(self, records: list) -> None:
        from app.store.observability import LogEntry, get_obs_session

        entries = []
        for record in records:
            try:
                event = to_event(record)
                event.pop("ts", None)
                cols = {c: event.pop(c, None) for c in _LOG_ENTRY_COLUMNS}
                entries.append(LogEntry(
                    ts=datetime.fromtimestamp(record.created, timezone.utc),
                    level=(cols["level"] or "")[:16],
                    logger=(cols["logger"] or "")[:128],
                    msg=cols["msg"] or "",
                    run_id=_as_int(cols["run_id"]),
                    kind=str(cols["kind"]) if cols["kind"] else None,
                    trace_id=cols["trace_id"],
                    span_id=cols["span_id"],
                    exc_info=cols["exc_info"],
                    extra=json.dumps(event, default=str),
                ))
            except Exception:
                pass  # skip a bad record, keep the batch
        if not entries:
            return
        try:
            with get_obs_session() as session:
                session.add_all(entries)
                session.commit()
        except Exception:
            pass  # DB unavailable: the lines are still on stdout

    def close(self):
        self._closed = True
        if self._timer is not None:
            try:
                self._timer.cancel()
            except Exception:
                pass
        with self._lock:
            records, self._buffer = self._buffer, []
            self._writing = True
        try:
            if records:
                self._persist(records)
        except Exception:
            pass
        finally:
            with self._lock:
                self._writing = False
        super().close()


_db_log_handler: DbLogHandler | None = None


def flush_db_logs() -> None:
    """Persist buffered records now (e.g. so a just-finished run's logs are queryable)."""
    if _db_log_handler is not None:
        _db_log_handler._flush()


def setup_logging() -> None:
    global _db_log_handler
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    root.setLevel(logging.INFO)
    for name, level in NOISE_LEVELS.items():
        logging.getLogger(name).setLevel(level)

    stdout = logging.StreamHandler()
    stdout.setFormatter(JsonFormatter())
    stdout.addFilter(ContextFilter())
    root.addHandler(stdout)

    _db_log_handler = DbLogHandler()
    root.addHandler(_db_log_handler)
```

- [ ] **Step 8: Store changes** in `api/app/store/observability.py`

Add `ObsMeta` after `LogEntry`, add three columns + an index to `LogEntry`, and extend `_migrate`:

```python
class LogEntry(ObsBase):
    # (existing docstring + columns unchanged) — add:
    __table_args__ = (
        Index("ix_log_entry_ts", "ts"),
        Index("ix_log_entry_run_id", "run_id"),
        Index("ix_log_entry_trace_id", "trace_id"),
    )
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    span_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    exc_info: Mapped[str | None] = mapped_column(Text, nullable=True)


class ObsMeta(ObsBase):
    """Key/value markers: one-time migrations done, followed semconv version."""
    __tablename__ = "obs_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
```

Inside `_migrate`, after the existing `run_log` block (same `with engine.begin() as conn:`), append:

```python
        log_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(log_entry)"))}
        log_additions = {
            "trace_id": "ALTER TABLE log_entry ADD COLUMN trace_id VARCHAR(32)",
            "span_id": "ALTER TABLE log_entry ADD COLUMN span_id VARCHAR(16)",
            "exc_info": "ALTER TABLE log_entry ADD COLUMN exc_info TEXT",
        }
        for col, ddl in log_additions.items():
            if col not in log_cols:
                conn.execute(text(ddl))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_log_entry_trace_id ON log_entry (trace_id)"))

        _scrub_secrets(conn)
```

And add these module-level helpers below `_migrate`:

```python
def _meta_get(conn, key: str) -> str | None:
    from sqlalchemy import text

    row = conn.execute(text("SELECT value FROM obs_meta WHERE key = :k"), {"k": key}).first()
    return row[0] if row else None


def _meta_set(conn, key: str, value: str) -> None:
    from sqlalchemy import text

    conn.execute(
        text("INSERT INTO obs_meta (key, value) VALUES (:k, :v) "
             "ON CONFLICT(key) DO UPDATE SET value = excluded.value"),
        {"k": key, "v": value},
    )


# Columns that v1 may have persisted with secrets in them.
_SCRUB_COLUMNS = {"log_entry": ("msg", "extra"), "run_log": ("logs", "error", "summary")}


def _scrub_secrets(conn) -> None:
    """One-time: mask secret values v1 persisted unredacted (httpx logged Telegram URLs
    containing the bot token). New rows are redacted at write time by log_schema."""
    from sqlalchemy import text

    from app.observability.redact import MASK, secret_values

    if _meta_get(conn, "scrub.secrets.v1"):
        return
    for value in secret_values():
        for table, cols in _SCRUB_COLUMNS.items():
            for col in cols:
                conn.execute(
                    text(f"UPDATE {table} SET {col} = replace({col}, :v, :m) WHERE instr({col}, :v) > 0"),
                    {"v": value, "m": MASK},
                )
    _meta_set(conn, "scrub.secrets.v1", utcnow().isoformat())
```

- [ ] **Step 9: Drop the per-run log blob path**

`api/app/observability/events.py` — `RunResult` loses `logs`:

```python
@dataclass(frozen=True)
class RunResult:
    status: str
    summary: str = ""
    error: str = ""
```

`api/app/observability/sink.py` `record_run`: delete the `_attach_buffer`/`_detach` import, the `handler` attach block, `_captured_logs()`, and the `_detach(handler)` in `finally`. Replace `_finish` with:

```python
    def _finish(status: str, *, summary: str, error: str) -> None:
        if run_id is None:
            return
        try:
            from app.logging_setup import flush_db_logs

            flush_db_logs()  # the run's last lines land in log_entry before it reads as finished
            sink.finish_run(run_id, RunResult(status, summary=summary, error=error))
        except Exception as ex:  # pragma: no cover - defensive
            logger.warning(f"observability: failed to finish run {run_id}: {ex}")
```

`api/app/observability/sqlite_sink.py`:
- `finish_run`: delete `run.logs = result.logs`.
- `get_run`: change `"logs": run.logs,` to `"logs": run.logs or _render_run_logs(session, run.id),`.
- `list_logs`: add `trace_id: str | None = None` param, filter `if trace_id: stmt = stmt.where(LogEntry.trace_id == trace_id)`, and add `"trace_id": r.trace_id, "span_id": r.span_id, "exc_info": r.exc_info,` to each returned dict. Mirror the new param in the `QueryProvider.list_logs` Protocol in `sink.py`.
- Add at module level:

```python
def _log_row_event(r: LogEntry) -> dict[str, Any]:
    """A stored log_entry row → the same event shape stdout prints (log_schema)."""
    import json

    event: dict[str, Any] = {
        "ts": _iso(r.ts), "level": r.level, "logger": r.logger, "msg": r.msg,
        "run_id": r.run_id, "kind": r.kind, "trace_id": r.trace_id,
        "span_id": r.span_id, "exc_info": r.exc_info,
    }
    try:
        event.update(json.loads(r.extra or "{}"))
    except ValueError:
        pass
    return event


def _render_run_logs(session, run_id: int, limit: int = 2000) -> str:
    from app.observability.log_schema import render

    rows = session.scalars(
        select(LogEntry).where(LogEntry.run_id == run_id).order_by(LogEntry.id.asc()).limit(limit)
    ).all()
    return "\n".join(render(_log_row_event(r)) for r in rows)
```

`api/app/api/routes.py` logs endpoint: add `trace_id: str = ""` to `get_obs_logs` params and pass `trace_id=trace_id or None` to `list_logs`.

- [ ] **Step 10: Run all backend tests**

Run: `cd api && uv run pytest -q`
Expected: PASS (all prior tests + new `test_log_schema.py`). If `test_db_log_handler_*` in `test_observability_logs.py` fail on `msg` now excluding the traceback, update their assertions to read `exc_info` — the traceback moved to its own column by design.

- [ ] **Step 11: Commit**

```bash
git add api/app/observability/redact.py api/app/observability/log_schema.py api/app/logging_setup.py \
  api/app/store/observability.py api/app/observability/events.py api/app/observability/sink.py \
  api/app/observability/sqlite_sink.py api/app/api/routes.py api/pyproject.toml api/uv.lock \
  api/tests/conftest.py api/tests/test_log_schema.py api/tests/test_observability.py api/tests/test_observability_logs.py
git commit -m "feat(obs): central log schema with redaction, noise policy and trace-ready log rows"
```

---

### Task 2: Tracing core — span storage, exporter, run spans

**Files:**
- Create: `api/app/observability/semconv.py`, `api/app/observability/tracing.py`, `api/app/observability/span_exporter.py`, `api/tests/test_tracing.py`
- Modify: `api/app/store/observability.py`, `api/app/observability/events.py`, `api/app/observability/sink.py`, `api/app/observability/sqlite_sink.py`, `api/app/config.py`, `api/app/main.py`, `api/tests/conftest.py`, `.env.example`

**Interfaces:**
- Consumes: `redact` (Task 1), `flush_db_logs` (Task 1), `_meta_set` (Task 1).
- Produces: `semconv` constants (names below); `tracing.init_tracing(*, exporter=None, simple=False)`, `tracing.shutdown_tracing()`, `tracing.get_tracer()`, `tracing.span(name, *, kind=SpanKind.INTERNAL, attributes=None)` (context manager yielding the span), `tracing.set_content(span, key, value)`, `tracing.trace_id_of(span) -> str | None`; `span_exporter.span_to_row(ReadableSpan) -> dict`, `SqliteSpanExporter`; `Span` model (columns per spec, `trace_id` nullable); `RunLog.trace_id`; `RunStart.trace_id`; settings `obs_capture_content: bool = True`, `obs_content_max_chars: int = 8000`; run span attributes `rotom.run.kind/source/id/status/summary`. Test fixture `traced` (obs_db + synchronous tracing).

- [ ] **Step 1: Settings** — in `api/app/config.py` under `# --- Observability ---` add:

```python
    # Capture LLM prompts/responses + tool args/results on spans (truncated + redacted).
    obs_capture_content: bool = True
    obs_content_max_chars: int = 8000  # per message / payload
```

Append to `.env.example` (new section at the end):

```bash
# ---- Observability ----
LOG_RETENTION_DAYS=14         # log_entry rows older than this are pruned (0 = keep all)
OBS_CAPTURE_CONTENT=true      # store LLM prompts/responses + tool payloads on spans (redacted)
OBS_CONTENT_MAX_CHARS=8000    # per-message cap for captured content
```

- [ ] **Step 2: Add the `traced` fixture** to `api/tests/conftest.py`:

```python
@pytest.fixture()
def traced(obs_db):
    """obs_db + a live TracerProvider exporting synchronously into the test DB."""
    from app.observability import tracing

    tracing.shutdown_tracing()
    tracing.init_tracing(simple=True)
    yield obs_db
    tracing.shutdown_tracing()


def span_rows(**filters):
    """All exported spans (ORM rows), optionally filtered by column equality."""
    from app.store.observability import Span, get_obs_session

    with get_obs_session() as s:
        q = s.query(Span)
        for col, value in filters.items():
            q = q.filter(getattr(Span, col) == value)
        return q.order_by(Span.start_time).all()
```

- [ ] **Step 3: Write the failing tests** — create `api/tests/test_tracing.py`:

```python
"""Tracing core: span export, record_run spans, context propagation, content capture."""

import asyncio
import json

import pytest

from tests.conftest import span_rows


def test_span_helper_exports_row(traced):
    from app.observability.tracing import span

    with span("unit.work", attributes={"rotom.count": 3}):
        pass
    (row,) = span_rows(name="unit.work")
    assert row.status == "UNSET"
    assert row.parent_span_id is None
    assert len(row.trace_id) == 32 and len(row.span_id) == 16
    assert json.loads(row.attributes)["rotom.count"] == 3
    assert row.duration_ms >= 0


def test_span_records_exception_as_error(traced):
    from app.observability.tracing import span

    with pytest.raises(ValueError):
        with span("unit.fail"):
            raise ValueError("nope")
    (row,) = span_rows(name="unit.fail")
    assert row.status == "ERROR"
    events = json.loads(row.events)
    assert events[0]["name"] == "exception"
    assert "nope" in events[0]["attributes"]["exception.message"]


def test_record_run_creates_root_span_and_links_trace_id(traced):
    from app.observability.sink import get_query_provider, record_run

    with record_run("gmail_triage", source="scheduler") as run:
        run.summary = "3 fetched"
    (root,) = span_rows(name="gmail_triage")
    detail = get_query_provider().get_run(run.run_id)
    assert detail["trace_id"] == root.trace_id
    assert root.run_id == int(run.run_id)
    attrs = json.loads(root.attributes)
    assert attrs["rotom.run.kind"] == "gmail_triage"
    assert attrs["rotom.run.source"] == "scheduler"
    assert attrs["rotom.run.status"] == "success"
    assert attrs["rotom.run.summary"] == "3 fetched"


def test_spans_inside_run_carry_run_id_and_nest(traced):
    from app.observability.sink import record_run
    from app.observability.tracing import span

    with record_run("k") as run:
        with span("inner.step"):
            pass
    (root,) = span_rows(name="k")
    (inner,) = span_rows(name="inner.step")
    assert inner.parent_span_id == root.span_id
    assert inner.trace_id == root.trace_id
    assert inner.run_id == int(run.run_id)


def test_nested_record_run_is_child_span(traced):
    from app.observability.sink import record_run

    with record_run("outer"):
        with record_run("inner"):
            pass
    (outer,) = span_rows(name="outer")
    (inner,) = span_rows(name="inner")
    assert inner.parent_span_id == outer.span_id


def test_failed_run_span_is_error(traced):
    from app.observability.sink import record_run

    with record_run("k") as run:
        run.fail(summary="2 accounts failed", error="quota")
    (root,) = span_rows(name="k")
    assert root.status == "ERROR"
    assert json.loads(root.attributes)["rotom.run.status"] == "failure"


def test_degraded_run_span_is_ok_with_status_attr(traced):
    from app.observability.sink import record_run

    with record_run("k") as run:
        run.degrade(summary="digest not sent")
    (root,) = span_rows(name="k")
    assert root.status != "ERROR"
    assert json.loads(root.attributes)["rotom.run.status"] == "degraded"


def test_record_run_without_tracing_still_works(obs_db):
    from app.observability.sink import get_query_provider, record_run

    with record_run("k") as run:
        pass
    detail = get_query_provider().get_run(run.run_id)
    assert detail["status"] == "success"
    assert detail["trace_id"] is None


async def test_to_thread_keeps_span_parent(traced):
    from app.observability.tracing import span

    def work():
        with span("thread.child"):
            pass

    with span("async.parent"):
        await asyncio.to_thread(work)
    (parent,) = span_rows(name="async.parent")
    (child,) = span_rows(name="thread.child")
    assert child.parent_span_id == parent.span_id


def test_set_content_truncates_and_redacts(traced, monkeypatch):
    from app.config import get_settings
    from app.observability.tracing import set_content, span

    monkeypatch.setattr(get_settings(), "obs_content_max_chars", 20)
    token = "1234567890:AAAbbbCCCdddEEEfffGGGhhhIIIjjjKKKlll0"
    with span("c") as s:
        set_content(s, "gen_ai.input.messages", [{"role": "user", "content": f"bot{token} " + "x" * 100}])
    (row,) = span_rows(name="c")
    raw = json.loads(row.attributes)["gen_ai.input.messages"]
    msgs = json.loads(raw)
    assert "1234567890:AAA" not in raw  # redacted BEFORE truncation — no partial token survives
    assert msgs[0]["content"].startswith("bot[REDACTED]")
    assert "…[+" in msgs[0]["content"]


def test_set_content_disabled(traced, monkeypatch):
    from app.config import get_settings
    from app.observability.tracing import set_content, span

    monkeypatch.setattr(get_settings(), "obs_capture_content", False)
    with span("c") as s:
        set_content(s, "gen_ai.input.messages", "secret prompt")
    (row,) = span_rows(name="c")
    assert "gen_ai.input.messages" not in json.loads(row.attributes)


def test_semconv_version_recorded(traced):
    from sqlalchemy import text

    from app.observability.semconv import SEMCONV_VERSION

    with traced._engine.connect() as conn:
        assert traced._meta_get(conn, "genai.semconv_version") == SEMCONV_VERSION


def test_log_lines_inside_run_carry_trace_id(traced):
    import logging

    from app.logging_setup import DbLogHandler
    from app.observability.sink import record_run
    from app.store.observability import LogEntry, get_obs_session

    handler = DbLogHandler()
    log = logging.getLogger("app.test.tracing")
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        with record_run("k"):
            log.info("inside")
        handler._flush()
    finally:
        log.removeHandler(handler)
        handler.close()
    (root,) = span_rows(name="k")
    with get_obs_session() as s:
        row = s.query(LogEntry).filter(LogEntry.msg == "inside").one()
    assert row.trace_id == root.trace_id
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_tracing.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.observability.tracing'`.

- [ ] **Step 5: Create `api/app/observability/semconv.py`**

```python
"""OpenTelemetry attribute names rotom emits — the ONE place they are spelled.

The OTel GenAI conventions are still "Development" stability; when upstream renames an
attribute, change it here (the version below is recorded in obs_meta). rotom-specific
attributes live under `rotom.*` so they never collide with upstream names.
"""

SEMCONV_VERSION = "gen-ai/1.42.0"

# --- GenAI (https://github.com/open-telemetry/semantic-conventions-genai) ---
OPERATION_NAME = "gen_ai.operation.name"
PROVIDER_NAME = "gen_ai.provider.name"
REQUEST_MODEL = "gen_ai.request.model"
RESPONSE_MODEL = "gen_ai.response.model"
RESPONSE_FINISH_REASONS = "gen_ai.response.finish_reasons"
USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
USAGE_CACHE_READ_INPUT_TOKENS = "gen_ai.usage.cache_read.input_tokens"
USAGE_REASONING_OUTPUT_TOKENS = "gen_ai.usage.reasoning.output_tokens"
INPUT_MESSAGES = "gen_ai.input.messages"
OUTPUT_MESSAGES = "gen_ai.output.messages"
CONVERSATION_ID = "gen_ai.conversation.id"
AGENT_NAME = "gen_ai.agent.name"
TOOL_NAME = "gen_ai.tool.name"
TOOL_CALL_ARGUMENTS = "gen_ai.tool.call.arguments"
TOOL_CALL_RESULT = "gen_ai.tool.call.result"
ERROR_TYPE = "error.type"

OP_CHAT = "chat"
OP_INVOKE_AGENT = "invoke_agent"
OP_EXECUTE_TOOL = "execute_tool"

# Attributes holding captured content (shown specially in the dashboard).
CONTENT_ATTRIBUTES = (INPUT_MESSAGES, OUTPUT_MESSAGES, TOOL_CALL_ARGUMENTS, TOOL_CALL_RESULT)

# --- HTTP (stable OTel conventions) ---
HTTP_METHOD = "http.request.method"
HTTP_ROUTE = "http.route"
HTTP_STATUS_CODE = "http.response.status_code"
URL_PATH = "url.path"

# --- rotom ---
ROTOM_RUN_ID = "rotom.run.id"
ROTOM_RUN_KIND = "rotom.run.kind"
ROTOM_RUN_SOURCE = "rotom.run.source"
ROTOM_RUN_STATUS = "rotom.run.status"
ROTOM_RUN_SUMMARY = "rotom.run.summary"
ROTOM_LLM_ROLE = "rotom.llm.role"
ROTOM_COST_USD = "rotom.cost_usd"
ROTOM_LEGACY = "rotom.legacy"

# rotom provider id (MODEL_PROVIDER / model prefix) → gen_ai.provider.name value
PROVIDER_NAMES = {"gemini": "gcp.gemini", "anthropic": "anthropic", "groq": "groq"}
# rotom provider id → genai-prices provider id
PRICING_PROVIDERS = {"gemini": "google", "anthropic": "anthropic", "groq": "groq"}
```

- [ ] **Step 6: Create `api/app/observability/span_exporter.py`**

```python
"""SqliteSpanExporter: finished OTel spans → the `span` table in observability.db.

Hot GenAI attributes are promoted to real columns so common SQL needs no JSON; the full
attribute map and span events are kept as JSON. Runs behind BatchSpanProcessor (prod)
or SimpleSpanProcessor (tests). Never raises: a failed batch is dropped with a warning.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Sequence

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from app.observability import semconv as sc
from app.observability.redact import redact

logger = logging.getLogger(__name__)


def _dt(ns: int | None) -> datetime | None:
    return datetime.fromtimestamp(ns / 1e9, timezone.utc) if ns else None


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def span_to_row(s: ReadableSpan) -> dict[str, Any]:
    ctx = s.context
    attrs = dict(s.attributes or {})
    start, end = s.start_time or 0, s.end_time or s.start_time or 0
    events = [
        {"name": e.name, "ts": _dt(e.timestamp).isoformat() if e.timestamp else None,
         "attributes": dict(e.attributes or {})}
        for e in s.events
    ]
    return {
        "span_id": format(ctx.span_id, "016x"),
        "trace_id": format(ctx.trace_id, "032x"),
        "parent_span_id": format(s.parent.span_id, "016x") if s.parent else None,
        "name": (s.name or "")[:256],
        "span_kind": s.kind.name,
        "start_time": _dt(start),
        "end_time": _dt(end),
        "duration_ms": (end - start) / 1e6,
        "status": s.status.status_code.name,
        "status_message": redact(s.status.description or ""),
        "run_id": _int(attrs.get(sc.ROTOM_RUN_ID)),
        "operation": attrs.get(sc.OPERATION_NAME),
        "provider": attrs.get(sc.PROVIDER_NAME),
        "model": attrs.get(sc.RESPONSE_MODEL) or attrs.get(sc.REQUEST_MODEL),
        "input_tokens": _int(attrs.get(sc.USAGE_INPUT_TOKENS)),
        "output_tokens": _int(attrs.get(sc.USAGE_OUTPUT_TOKENS)),
        "cache_read_tokens": _int(attrs.get(sc.USAGE_CACHE_READ_INPUT_TOKENS)),
        "reasoning_tokens": _int(attrs.get(sc.USAGE_REASONING_OUTPUT_TOKENS)),
        "cost_usd": _float(attrs.get(sc.ROTOM_COST_USD)),
        "attributes": redact(json.dumps(attrs, default=str, ensure_ascii=False)),
        "events": redact(json.dumps(events, default=str, ensure_ascii=False)),
    }


class SqliteSpanExporter(SpanExporter):
    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        from sqlalchemy import insert

        from app.store.observability import Span, get_obs_session

        try:
            rows = [span_to_row(s) for s in spans]
            if rows:
                with get_obs_session() as session:
                    session.execute(insert(Span).prefix_with("OR IGNORE"), rows)
                    session.commit()
            return SpanExportResult.SUCCESS
        except Exception:
            logger.warning("span export failed; dropped %d span(s)", len(spans), exc_info=True)
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True
```

- [ ] **Step 7: Create `api/app/observability/tracing.py`**

```python
"""OpenTelemetry wiring: rotom's TracerProvider → SqliteSpanExporter → `span` table.

rotom owns its provider (it is NOT installed as the OTel global) so tests can re-init
freely; the OTel *context* is global regardless, so `trace.get_current_span()` (used for
log correlation) sees every span started here. Until `init_tracing()` runs, `get_tracer()`
is a no-op tracer and all instrumentation is inert.

Always call `get_tracer()` at use time — never cache a tracer at import.
"""

import json
import logging
from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter

from app.observability import semconv as sc
from app.observability.redact import redact

logger = logging.getLogger(__name__)

_provider: TracerProvider | None = None
_NOOP = trace.NoOpTracer()


class RunAttributionProcessor(SpanProcessor):
    """Stamp `rotom.run.id` on every span started inside a run (via the run ContextVar)."""

    def on_start(self, span, parent_context=None) -> None:
        from app.observability.sink import current_run_id

        run_id = current_run_id.get()
        if run_id is not None and sc.ROTOM_RUN_ID not in (span.attributes or {}):
            try:
                span.set_attribute(sc.ROTOM_RUN_ID, int(run_id))
            except (TypeError, ValueError):
                pass


def init_tracing(*, exporter: SpanExporter | None = None, simple: bool = False) -> None:
    """Install rotom's TracerProvider. Idempotent; `simple=True` exports synchronously (tests)."""
    global _provider
    if _provider is not None:
        return
    from app.observability.span_exporter import SqliteSpanExporter

    provider = TracerProvider(resource=Resource.create({"service.name": "rotom"}))
    provider.add_span_processor(RunAttributionProcessor())
    exp = exporter or SqliteSpanExporter()
    provider.add_span_processor(
        SimpleSpanProcessor(exp) if simple else BatchSpanProcessor(exp, schedule_delay_millis=2000)
    )
    _provider = provider


def shutdown_tracing() -> None:
    """Flush pending spans and drop the provider (process exit / test teardown)."""
    global _provider
    if _provider is not None:
        try:
            _provider.shutdown()
        except Exception:  # pragma: no cover - defensive
            logger.warning("tracing shutdown failed", exc_info=True)
        _provider = None


def get_tracer() -> trace.Tracer:
    return _provider.get_tracer("rotom") if _provider is not None else _NOOP


@contextmanager
def span(
    name: str,
    *,
    kind: trace.SpanKind = trace.SpanKind.INTERNAL,
    attributes: dict[str, Any] | None = None,
) -> Iterator[trace.Span]:
    """A current span for a unit of work; exceptions are recorded and mark it ERROR."""
    with get_tracer().start_as_current_span(name, kind=kind, attributes=attributes or {}) as s:
        yield s


def trace_id_of(s: trace.Span) -> str | None:
    ctx = s.get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]}…[+{len(text) - limit} chars]"


def _clip(value: Any, limit: int) -> Any:
    if isinstance(value, str):
        return _truncate(redact(value), limit)  # redact first: truncation could split a secret
    if isinstance(value, dict):
        return {k: _clip(v, limit) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clip(v, limit) for v in value]
    return value


def set_content(s: trace.Span, key: str, value: Any) -> None:
    """Attach captured content (prompt/response/tool payload): per-string truncated,
    JSON-encoded, secret-redacted. No-op when capture is off or the span isn't recording."""
    try:
        from app.config import get_settings

        settings = get_settings()
        if not settings.obs_capture_content or not s.is_recording():
            return
        clipped = _clip(value, settings.obs_content_max_chars)
        encoded = clipped if isinstance(clipped, str) else json.dumps(clipped, default=str, ensure_ascii=False)
        s.set_attribute(key, redact(encoded))
    except Exception:  # pragma: no cover - defensive
        logger.warning("content capture failed for %s", key, exc_info=True)
```

- [ ] **Step 8: Store** — in `api/app/store/observability.py` add `Float` to the sqlalchemy import, `RunLog.trace_id` (+ index), the `Span` model, the run_log migration column, and the semconv marker:

```python
class RunLog(ObsBase):
    __tablename__ = "run_log"
    __table_args__ = (
        Index("ix_run_log_parent_run_id", "parent_run_id"),
        Index("ix_run_log_trace_id", "trace_id"),
    )
    # … existing columns …
    # OTel trace this run's root span belongs to (NULL for pre-tracing runs).
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)


class Span(ObsBase):
    """One finished OTel span. GenAI hot fields are promoted to columns; everything
    else stays in `attributes` (JSON). `trace_id` is NULL only for backfilled v1 LLM rows."""
    __tablename__ = "span"
    __table_args__ = (
        Index("ix_span_trace_id", "trace_id"),
        Index("ix_span_start_time", "start_time"),
        Index("ix_span_run_id", "run_id"),
        Index("ix_span_operation", "operation"),
    )

    span_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    parent_span_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    name: Mapped[str] = mapped_column(String(256))
    span_kind: Mapped[str] = mapped_column(String(16), default="INTERNAL")
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(8), default="UNSET")
    status_message: Mapped[str] = mapped_column(Text, default="")
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    operation: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    attributes: Mapped[str] = mapped_column(Text, default="{}")
    events: Mapped[str] = mapped_column(Text, default="[]")
```

In `_migrate`, add `"trace_id": "ALTER TABLE run_log ADD COLUMN trace_id VARCHAR(32)",` to `run_additions`, then after the parent index:

```python
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_run_log_trace_id ON run_log (trace_id)"))
```

and at the end of `_migrate` (after `_scrub_secrets(conn)`):

```python
        from app.observability.semconv import SEMCONV_VERSION

        _meta_set(conn, "genai.semconv_version", SEMCONV_VERSION)
```

- [ ] **Step 9: Run spans** — `api/app/observability/events.py`: add `trace_id: str | None = None` to `RunStart`. `api/app/observability/sqlite_sink.py`: `start_run` passes `trace_id=run.trace_id` into `RunLog(...)`; add `"trace_id": r.trace_id` to `list_runs` dicts and `"trace_id": run.trace_id` to `get_run`.

Rewrite `record_run` in `api/app/observability/sink.py` (keep the docstring; add one sentence: "The run is also the root (or child) OTel span of its trace; `run_log.trace_id` links them."):

```python
@contextmanager
def record_run(
    kind: str,
    *,
    source: str = "system",
    external_id: str | None = None,
    external_url: str | None = None,
):
    # (docstring as before + the trace sentence)
    from opentelemetry.trace import Status, StatusCode

    from app.observability import semconv as sc
    from app.observability.tracing import get_tracer, trace_id_of
    from app.store.observability import RunStatus

    sink = get_sink()
    parent = current_run_id.get()  # capture BEFORE we overwrite current_run_id

    with get_tracer().start_as_current_span(
        kind, attributes={sc.ROTOM_RUN_KIND: kind, sc.ROTOM_RUN_SOURCE: source}
    ) as run_span:
        run_id: str | None = None
        try:
            run_id = sink.start_run(RunStart(
                kind=kind, source=source, external_id=external_id, external_url=external_url,
                parent_run_id=parent, trace_id=trace_id_of(run_span),
            ))
        except Exception as ex:  # pragma: no cover - defensive
            logger.warning(f"observability: failed to start run {kind!r}: {ex}")
        if run_id is not None:
            run_span.set_attribute(sc.ROTOM_RUN_ID, int(run_id))

        token = current_run_id.set(run_id)
        kind_token = current_run_kind.set(kind)
        ctx = RunContext(run_id)

        stop_beat = threading.Event()
        beat_thread = None
        if run_id is not None:
            def _beat() -> None:
                while not stop_beat.wait(HEARTBEAT_INTERVAL):
                    try:
                        sink.heartbeat(run_id)
                    except Exception:  # pragma: no cover - defensive
                        pass
            beat_thread = threading.Thread(target=_beat, name=f"run-heartbeat-{run_id}", daemon=True)
            beat_thread.start()

        def _finish(status: str, *, summary: str, error: str) -> None:
            run_span.set_attribute(sc.ROTOM_RUN_STATUS, str(status))
            if summary:
                run_span.set_attribute(sc.ROTOM_RUN_SUMMARY, summary)
            if status == RunStatus.FAILURE:
                run_span.set_status(Status(StatusCode.ERROR, error or summary or "failed"))
            if run_id is None:
                return
            try:
                from app.logging_setup import flush_db_logs

                flush_db_logs()
                sink.finish_run(run_id, RunResult(status, summary=summary, error=error))
            except Exception as ex:  # pragma: no cover - defensive
                logger.warning(f"observability: failed to finish run {run_id}: {ex}")

        try:
            yield ctx
        except Exception as exc:
            _finish(RunStatus.FAILURE, summary=ctx.summary or "Failed", error=ctx.error or str(exc))
            raise
        else:
            if ctx._failed:
                status = RunStatus.FAILURE
            elif ctx._degraded:
                status = RunStatus.DEGRADED
            else:
                status = RunStatus.SUCCESS
            _finish(status, summary=ctx.summary, error=ctx.error)
        finally:
            stop_beat.set()
            if beat_thread is not None:
                beat_thread.join(timeout=2)
            current_run_id.reset(token)
            current_run_kind.reset(kind_token)
```

- [ ] **Step 10: Wire into the process** — `api/app/main.py`: after `init_obs_db()` add

```python
    from app.observability.tracing import init_tracing, shutdown_tracing

    init_tracing()
```

and as the last line of the `finally:` block: `shutdown_tracing()  # flush pending spans`.

- [ ] **Step 11: Run all backend tests**

Run: `cd api && uv run pytest -q`
Expected: PASS.

- [ ] **Step 12: Commit**

```bash
git add api/app/observability/semconv.py api/app/observability/tracing.py api/app/observability/span_exporter.py \
  api/app/store/observability.py api/app/observability/events.py api/app/observability/sink.py \
  api/app/observability/sqlite_sink.py api/app/config.py api/app/main.py .env.example \
  api/tests/conftest.py api/tests/test_tracing.py
git commit -m "feat(obs): OpenTelemetry tracing into a local span table; runs are root spans"
```

---

### Task 3: LLM spans, cost, and retiring `llm_usage`

**Files:**
- Create: `api/app/observability/pricing.py`, `api/app/observability/llm_tracing.py`, `api/tests/test_llm_tracing.py`
- Modify: `api/app/llm/provider.py`, `api/app/observability/events.py`, `api/app/observability/sink.py`, `api/app/observability/sqlite_sink.py`, `api/app/store/observability.py`, `api/pyproject.toml`, `api/tests/test_observability_logs.py`, `api/tests/test_provider.py`

**Interfaces:**
- Consumes: `semconv` (`PROVIDER_NAMES`, `PRICING_PROVIDERS`, GenAI names), `tracing.get_tracer/set_content`, `Span`, `_meta_get/_meta_set`.
- Produces: `pricing.cost_usd(provider, model, *, input_tokens, output_tokens, cache_read_tokens=0) -> float | None`; `llm_tracing.LlmTracingCallback(provider, model, role)`; `get_run()["metrics"]` items `{model, calls, input_tokens, output_tokens, avg_latency_ms, cost_usd}` computed from `span`; `UsageEvent`, `UsageCallback`, `record_usage` no longer exist.

- [ ] **Step 1: Add dependency**

Run: `cd api && uv add "genai-prices>=0.1.9"`

- [ ] **Step 2: Write the failing tests** — create `api/tests/test_llm_tracing.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_llm_tracing.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.observability.pricing'`.

- [ ] **Step 4: Create `api/app/observability/pricing.py`**

```python
"""LLM cost via genai-prices (bundled, offline price data — no network).

Price on the *resolved* model the provider reports (e.g. `gemini-3-flash-preview`);
aliases like `gemini-flash-latest` aren't in the price table and return None. Never raises.
Token semantics: `input_tokens` includes cached tokens (passed again as
`cache_read_tokens`, priced at the cache rate); Gemini's `output_tokens` already
include thinking tokens.
"""

import logging

from app.observability.semconv import PRICING_PROVIDERS

logger = logging.getLogger(__name__)


def cost_usd(
    provider: str,
    model: str | None,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
) -> float | None:
    if not model:
        return None
    ref = model.removeprefix("models/")
    try:
        from genai_prices import Usage, calc_price

        price = calc_price(
            Usage(
                input_tokens=input_tokens or 0,
                output_tokens=output_tokens or 0,
                cache_read_tokens=cache_read_tokens or None,
            ),
            model_ref=ref,
            provider_id=PRICING_PROVIDERS.get(provider, provider),
        )
        return float(price.total_price)
    except LookupError:
        return None
    except Exception:
        logger.debug("pricing failed for %s/%s", provider, model, exc_info=True)
        return None
```

- [ ] **Step 5: Create `api/app/observability/llm_tracing.py`**

```python
"""LlmTracingCallback: one `chat {model}` CLIENT span per LLM call (OTel GenAI semconv).

The span's parent is whatever span is current when the call starts — LangChain copies
contextvars into its callback hops, so calls made inside a run/step/tool nest under it.
In-flight spans are keyed by LangChain's per-call run id and always ended, on success
(`on_llm_end`) or failure (`on_llm_error`).
"""

import logging
import threading
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from opentelemetry.trace import SpanKind, Status, StatusCode

from app.observability import semconv as sc
from app.observability.pricing import cost_usd
from app.observability.tracing import get_tracer, set_content

logger = logging.getLogger(__name__)

_ROLES = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}


def _text(content: Any) -> str:
    from app.llm.provider import extract_text  # lazy: provider imports this module

    return extract_text(content)


def _message(m: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"role": _ROLES.get(getattr(m, "type", ""), getattr(m, "type", "unknown")),
                           "content": _text(getattr(m, "content", ""))}
    calls = getattr(m, "tool_calls", None)
    if calls:
        out["tool_calls"] = [{"name": c.get("name"), "args": c.get("args")} for c in calls]
    return out


def _usage(response: LLMResult) -> dict[str, Any]:
    u: dict[str, Any] = {"input": 0, "output": 0, "cache_read": 0, "reasoning": 0,
                         "model": None, "finish": [], "messages": []}
    llm_output = response.llm_output or {}
    token_usage = llm_output.get("token_usage") or {}
    u["input"] = token_usage.get("prompt_tokens", 0) or 0
    u["output"] = token_usage.get("completion_tokens", 0) or 0
    u["model"] = llm_output.get("model_name") or llm_output.get("model")
    for generations in response.generations:
        for g in generations:
            message = getattr(g, "message", None)
            finish = (g.generation_info or {}).get("finish_reason")
            if message is not None:
                um = getattr(message, "usage_metadata", None)
                if um:
                    u["input"] = um.get("input_tokens", u["input"]) or 0
                    u["output"] = um.get("output_tokens", u["output"]) or 0
                    u["cache_read"] = (um.get("input_token_details") or {}).get("cache_read", 0) or 0
                    u["reasoning"] = (um.get("output_token_details") or {}).get("reasoning", 0) or 0
                rm = getattr(message, "response_metadata", None) or {}
                u["model"] = rm.get("model_name") or rm.get("model") or u["model"]
                finish = finish or rm.get("finish_reason") or rm.get("stop_reason")
                u["messages"].append(_message(message))
            else:
                u["messages"].append({"role": "assistant", "content": g.text})
            if finish:
                u["finish"].append(str(finish))
    return u


class LlmTracingCallback(BaseCallbackHandler):
    def __init__(self, provider: str, model: str, role: str):
        self.provider = provider
        self.model = model
        self.role = role
        self._spans: dict[str, Any] = {}
        self._lock = threading.Lock()

    def _start(self, run_id, messages: list[dict[str, Any]]) -> None:
        if run_id is None:
            return
        try:
            s = get_tracer().start_span(
                f"chat {self.model}",
                kind=SpanKind.CLIENT,
                attributes={
                    sc.OPERATION_NAME: sc.OP_CHAT,
                    sc.PROVIDER_NAME: sc.PROVIDER_NAMES.get(self.provider, self.provider),
                    sc.REQUEST_MODEL: self.model,
                    sc.ROTOM_LLM_ROLE: self.role,
                },
            )
            set_content(s, sc.INPUT_MESSAGES, messages)
            with self._lock:
                self._spans[str(run_id)] = s
        except Exception:
            logger.warning("LLM span start failed", exc_info=True)

    def _pop(self, run_id):
        if run_id is None:
            return None
        with self._lock:
            return self._spans.pop(str(run_id), None)

    def on_chat_model_start(self, serialized, messages, *, run_id=None, **kwargs) -> None:
        self._start(run_id, [_message(m) for batch in messages for m in batch])

    def on_llm_start(self, serialized, prompts, *, run_id=None, **kwargs) -> None:
        self._start(run_id, [{"role": "user", "content": p} for p in prompts])

    def on_llm_end(self, response: LLMResult, *, run_id=None, **kwargs) -> None:
        s = self._pop(run_id)
        if s is None:
            return
        try:
            u = _usage(response)
            resp_model = u["model"] or self.model
            cost = cost_usd(self.provider, resp_model, input_tokens=u["input"],
                            output_tokens=u["output"], cache_read_tokens=u["cache_read"])
            if cost is None and resp_model != self.model:
                cost = cost_usd(self.provider, self.model, input_tokens=u["input"],
                                output_tokens=u["output"], cache_read_tokens=u["cache_read"])
            s.set_attribute(sc.RESPONSE_MODEL, resp_model)
            s.set_attribute(sc.USAGE_INPUT_TOKENS, int(u["input"]))
            s.set_attribute(sc.USAGE_OUTPUT_TOKENS, int(u["output"]))
            if u["cache_read"]:
                s.set_attribute(sc.USAGE_CACHE_READ_INPUT_TOKENS, int(u["cache_read"]))
            if u["reasoning"]:
                s.set_attribute(sc.USAGE_REASONING_OUTPUT_TOKENS, int(u["reasoning"]))
            if u["finish"]:
                s.set_attribute(sc.RESPONSE_FINISH_REASONS, u["finish"])
            if cost is not None:
                s.set_attribute(sc.ROTOM_COST_USD, cost)
            set_content(s, sc.OUTPUT_MESSAGES, u["messages"])
        except Exception:
            logger.warning("LLM span finish failed", exc_info=True)
        finally:
            s.end()

    def on_llm_error(self, error: BaseException, *, run_id=None, **kwargs) -> None:
        s = self._pop(run_id)
        if s is None:
            return
        try:
            s.record_exception(error)
            s.set_attribute(sc.ERROR_TYPE, type(error).__name__)
            s.set_status(Status(StatusCode.ERROR, str(error)[:500]))
        finally:
            s.end()
```

- [ ] **Step 6: Use it in the provider** — in `api/app/llm/provider.py` delete the `UsageCallback` class, the `LLMResult`/`BaseCallbackHandler` imports, and the `UsageEvent`/`get_sink`/`current_run_id` imports; add `from app.observability.llm_tracing import LlmTracingCallback`; replace `cb = UsageCallback(provider, model_name, role)` with `cb = LlmTracingCallback(provider, model_name, role)`.

- [ ] **Step 7: Retire the usage path**
- `events.py`: delete `UsageEvent` (and the now-unused `datetime` import).
- `sink.py`: delete `record_usage` from `ObservabilitySink` and from `CompositeSink`; drop the `UsageEvent` import.
- `sqlite_sink.py`: delete `record_usage`; replace the `metrics` query in `get_run` with:

```python
            stmt = select(
                Span.model,
                func.count().label("calls"),
                func.sum(Span.input_tokens).label("in_tokens"),
                func.sum(Span.output_tokens).label("out_tokens"),
                func.avg(Span.duration_ms).label("avg_latency_ms"),
                func.sum(Span.cost_usd).label("cost_usd"),
            ).where(Span.run_id == run.id, Span.operation == "chat").group_by(Span.model)

            metrics = [
                {
                    "model": row.model,
                    "calls": int(row.calls),
                    "input_tokens": int(row.in_tokens or 0),
                    "output_tokens": int(row.out_tokens or 0),
                    "avg_latency_ms": int(row.avg_latency_ms) if row.avg_latency_ms is not None else None,
                    "cost_usd": float(row.cost_usd) if row.cost_usd is not None else None,
                }
                for row in session.execute(stmt)
            ]
```

(import `Span` from `app.store.observability`). Leave `usage_by_model_day` untouched — Task 7 deletes it with the old page.
- `api/tests/test_observability_logs.py`: delete the "Feature B" sections that use `UsageEvent`, `record_usage`, `UsageCallback` (tests `test_usage_event_*`, `test_sqlite_sink_persists_latency`, `test_sqlite_sink_latency_none_is_stored_as_null`, `test_get_run_includes_avg_latency_in_metrics`, `test_usage_by_model_day_includes_avg_latency`, `test_usage_callback_*`) — superseded by `test_llm_tracing.py`.

- [ ] **Step 8: Backfill** — in `api/app/store/observability.py` add below `_scrub_secrets`, and call `_backfill_llm_usage(conn)` from `_migrate` right after `_scrub_secrets(conn)`:

```python
def _backfill_llm_usage(conn) -> None:
    """One-time: copy v1 `llm_usage` rows into `span` (operation='chat', trace_id NULL —
    they predate tracing) so LLM stats/cost cover history. llm_usage is no longer written."""
    import json
    from datetime import timedelta

    from sqlalchemy import insert, select

    from app.observability import semconv as sc
    from app.observability.pricing import cost_usd

    if _meta_get(conn, "backfill.llm_usage.v1"):
        return
    rows = []
    for u in conn.execute(select(LLMUsage.__table__)).mappings():
        end = u["ts"]
        if end is not None and end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        duration = float(u["latency_ms"] or 0)
        rows.append({
            "span_id": f"l{u['id']:015d}",
            "trace_id": None,
            "parent_span_id": None,
            "name": f"chat {u['model']}",
            "span_kind": "CLIENT",
            "start_time": end - timedelta(milliseconds=duration),
            "end_time": end,
            "duration_ms": duration,
            "status": "UNSET",
            "status_message": "",
            "run_id": u["run_id"],
            "operation": sc.OP_CHAT,
            "provider": sc.PROVIDER_NAMES.get(u["provider"], u["provider"]),
            "model": u["model"],
            "input_tokens": u["input_tokens"],
            "output_tokens": u["output_tokens"],
            "cost_usd": cost_usd(u["provider"], u["model"], input_tokens=u["input_tokens"],
                                 output_tokens=u["output_tokens"]),
            "attributes": json.dumps({sc.ROTOM_LLM_ROLE: u["role"], sc.ROTOM_LEGACY: True}),
            "events": "[]",
        })
    if rows:
        conn.execute(insert(Span.__table__).prefix_with("OR IGNORE"), rows)
    _meta_set(conn, "backfill.llm_usage.v1", utcnow().isoformat())
```

(The `Span` class must be defined above `_migrate` in the module, which it is after Task 2.)

- [ ] **Step 9: Run all backend tests**

Run: `cd api && uv run pytest -q`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add api/app/observability/pricing.py api/app/observability/llm_tracing.py api/app/llm/provider.py \
  api/app/observability/events.py api/app/observability/sink.py api/app/observability/sqlite_sink.py \
  api/app/store/observability.py api/pyproject.toml api/uv.lock api/tests/test_llm_tracing.py \
  api/tests/test_observability_logs.py
git commit -m "feat(obs): GenAI chat spans with cost, cached/reasoning tokens and content; retire llm_usage"
```

---

### Task 4: Agent, tool and triage-pipeline spans

**Files:**
- Modify: `api/app/agent/graph.py`, `api/app/agent/toolkit.py`, `api/app/tools/gmail/pipeline.py`, `api/tests/test_pipeline.py`
- Create: `api/tests/test_agent_tracing.py`

**Interfaces:**
- Consumes: `tracing.get_tracer/span/set_content`, `semconv`.
- Produces: `invoke_agent rotom` span per chat turn (attributes `gen_ai.operation.name=invoke_agent`, `gen_ai.agent.name=rotom`, `gen_ai.conversation.id=<thread_id>`); `execute_tool {name}` span per tool call; `toolkit.traced_tool(tool) -> tool`; triage spans `triage.fetch`, `gmail.fetch {account}`, `triage.dedup`, `triage.screen`, `triage.classify`, `triage.draft`, `triage.store` with `rotom.triage.*` count attributes.

- [ ] **Step 1: Write the failing tests** — create `api/tests/test_agent_tracing.py`:

```python
"""Agent turn + tool spans."""

import json

from langchain_core.messages import AIMessage

from tests.conftest import span_rows


async def test_run_agent_span_wraps_tool_spans(traced, session_db, monkeypatch):
    from app.agent import graph, toolkit

    class FakeAgent:
        async def ainvoke(self, state, config):
            await toolkit.get_current_time.ainvoke({})
            return {"messages": [AIMessage(content="It is noon.")]}

    async def fake_get_agent():
        return FakeAgent()

    monkeypatch.setattr(graph, "get_agent", fake_get_agent)
    reply = await graph.run_agent("what time is it?", thread_id="42")
    assert reply == "It is noon."

    (agent,) = span_rows(operation="invoke_agent")
    (tool,) = span_rows(operation="execute_tool")
    assert agent.name == "invoke_agent rotom"
    assert tool.name == "execute_tool get_current_time"
    assert tool.parent_span_id == agent.span_id
    attrs = json.loads(agent.attributes)
    assert attrs["gen_ai.conversation.id"] == "42"
    assert json.loads(attrs["gen_ai.output.messages"])[0]["content"] == "It is noon."
    assert "timezone" in json.loads(tool.attributes)["gen_ai.tool.call.result"]


def test_sync_tool_span_captures_args_and_result(traced, session_db):
    from app.agent import toolkit

    toolkit.list_emails.invoke({"category": "critical", "limit": 3})
    (tool,) = span_rows(operation="execute_tool")
    attrs = json.loads(tool.attributes)
    assert attrs["gen_ai.tool.name"] == "list_emails"
    assert json.loads(attrs["gen_ai.tool.call.arguments"]) == {"category": "critical", "limit": 3}


def test_tool_error_marks_span_error(traced):
    import pytest
    from langchain_core.tools import tool

    from app.agent.toolkit import traced_tool

    @tool
    def explode(x: int) -> str:
        """Always fails."""
        raise RuntimeError("kaboom")

    t = traced_tool(explode)
    with pytest.raises(RuntimeError):
        t.invoke({"x": 1})
    (row,) = span_rows(operation="execute_tool")
    assert row.status == "ERROR"


def test_all_tools_are_traced_and_keep_schemas():
    from app.agent.toolkit import ALL_TOOLS

    for t in ALL_TOOLS:
        fn = t.coroutine or t.func
        assert getattr(fn, "__rotom_traced__", False), t.name
    names = {t.name for t in ALL_TOOLS}
    assert {"list_emails", "create_reminder", "run_gmail_triage"} <= names
```

Append to `api/tests/test_pipeline.py`:

```python
def test_triage_emits_step_spans(session_db, traced):
    import json

    from app.observability.tracing import span
    from tests.conftest import span_rows

    fetchers = [FakeFetcher("personal", [make_email(message_id="s1")]),
                FakeFetcher("work", RuntimeError("quota"))]
    with span("root"):
        run_triage(fetchers, classify_all_as("needs_reply"), fake_draft_fn)

    names = [r.name for r in span_rows()]
    for expected in ("triage.fetch", "gmail.fetch personal", "gmail.fetch work",
                     "triage.dedup", "triage.classify", "triage.draft", "triage.store"):
        assert expected in names
    (fetch,) = span_rows(name="triage.fetch")
    (root,) = span_rows(name="root")
    assert fetch.parent_span_id == root.span_id
    assert json.loads(fetch.attributes)["rotom.triage.fetched"] == 1
    (failed,) = span_rows(name="gmail.fetch work")
    assert failed.status == "ERROR"
    (store,) = span_rows(name="triage.store")
    assert json.loads(store.attributes)["rotom.triage.stored"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_agent_tracing.py tests/test_pipeline.py -q`
Expected: FAIL (no `invoke_agent`/`execute_tool`/`triage.*` spans; `traced_tool` missing).

- [ ] **Step 3: Agent span** — replace `run_agent` in `api/app/agent/graph.py`:

```python
async def run_agent(message: str, thread_id: str) -> str:
    """Send one user message through the agent; return its final text reply.

    The whole turn is one `invoke_agent rotom` span; the agent's LLM calls and tool
    spans nest under it."""
    from app.llm.provider import extract_text
    from app.observability import semconv as sc
    from app.observability.tracing import get_tracer, set_content

    agent = await get_agent()
    with get_tracer().start_as_current_span(
        "invoke_agent rotom",
        attributes={sc.OPERATION_NAME: sc.OP_INVOKE_AGENT, sc.AGENT_NAME: "rotom",
                    sc.CONVERSATION_ID: thread_id},
    ) as turn:
        set_content(turn, sc.INPUT_MESSAGES, [{"role": "user", "content": message}])
        state = await agent.ainvoke(
            {"messages": [{"role": "user", "content": message}]},
            config={"configurable": {"thread_id": thread_id}, "recursion_limit": 25},
        )
        reply = extract_text(state["messages"][-1].content) or "(no reply)"
        set_content(turn, sc.OUTPUT_MESSAGES, [{"role": "assistant", "content": reply}])
        return reply
```

- [ ] **Step 4: Tool spans** — in `api/app/agent/toolkit.py`, add near the top (after imports):

```python
import functools

from langchain_core.tools import BaseTool


def traced_tool(t: BaseTool) -> BaseTool:
    """Make every call of `t` an `execute_tool {name}` span that is *current* while the
    tool runs, so LLM calls / runs it triggers nest under it. Schema and name unchanged."""
    from app.observability import semconv as sc
    from app.observability.tracing import get_tracer, set_content

    def _span():
        return get_tracer().start_as_current_span(
            f"execute_tool {t.name}",
            attributes={sc.OPERATION_NAME: sc.OP_EXECUTE_TOOL, sc.TOOL_NAME: t.name},
        )

    if t.coroutine is not None and not getattr(t.coroutine, "__rotom_traced__", False):
        original_async = t.coroutine

        @functools.wraps(original_async)
        async def traced_async(*args, **kwargs):
            with _span() as s:
                set_content(s, sc.TOOL_CALL_ARGUMENTS, kwargs)
                result = await original_async(*args, **kwargs)
                set_content(s, sc.TOOL_CALL_RESULT, result)
                return result

        traced_async.__rotom_traced__ = True
        t.coroutine = traced_async

    if t.func is not None and not getattr(t.func, "__rotom_traced__", False):
        original_sync = t.func

        @functools.wraps(original_sync)
        def traced_sync(*args, **kwargs):
            with _span() as s:
                set_content(s, sc.TOOL_CALL_ARGUMENTS, kwargs)
                result = original_sync(*args, **kwargs)
                set_content(s, sc.TOOL_CALL_RESULT, result)
                return result

        traced_sync.__rotom_traced__ = True
        t.func = traced_sync
    return t
```

and change the `ALL_TOOLS` definition to:

```python
ALL_TOOLS = [traced_tool(t) for t in (
    run_gmail_triage, list_emails, get_email, draft_reply_tool, list_drafts,
    get_current_time, create_reminder, list_reminders, cancel_reminder,
    run_workflow, work_on_issue,
)]
```

- [ ] **Step 5: Triage step spans** — in `api/app/tools/gmail/pipeline.py` add `from app.observability.tracing import span` to the imports and wrap each step of `run_triage` (logic unchanged; only the `with` blocks and `set_attribute` lines are new):

```python
def run_triage(fetchers, classify_fn, draft_fn, max_per_account: int = 50, *, screen_fn=None) -> TriageResult:
    """Run one triage pass across all accounts. Never raises for per-account failures."""
    result = TriageResult()

    # 1. Fetch (degraded-state: one account failing doesn't kill the run)
    fetched: list[dict] = []
    with span("triage.fetch") as step:
        logger.info("Starting email fetch across %d accounts", len(fetchers))
        for fetcher in fetchers:
            try:
                with span(f"gmail.fetch {fetcher.account}", attributes={"rotom.gmail.account": fetcher.account}) as fs:
                    logger.info("Fetching unread for account %s", fetcher.account)
                    f = fetcher.fetch_unread(max_results=max_per_account)
                    fs.set_attribute("rotom.triage.fetched", len(f))
                logger.info("Fetched %d emails from %s", len(f), fetcher.account)
                fetched.extend(f)
            except Exception as exc:  # noqa: BLE001 — degraded-state reporting by design
                logger.exception("Fetch failed for account %s", fetcher.account)
                result.errors[fetcher.account] = f"fetch failed: {exc}"
        result.fetched = len(fetched)
        step.set_attribute("rotom.triage.fetched", len(fetched))
        step.set_attribute("rotom.triage.account_errors", len(result.errors))

    # 2. Dedup against the processed-messages ledger
    with span("triage.dedup") as step:
        with get_session() as session:
            seen = {
                (p.account, p.message_id)
                for p in session.query(ProcessedMessage).filter(
                    ProcessedMessage.message_id.in_([e["message_id"] for e in fetched] or [""])
                )
            }
        new = [e for e in fetched if (e["account"], e["message_id"]) not in seen]
        step.set_attribute("rotom.triage.new", len(new))
    logger.info("Dedup complete: %d new un-processed emails found out of %d fetched", len(new), len(fetched))
    if not new:
        return result

    # 3. Screen for prompt injection (if screen_fn provided)
    quarantined_dicts: list[dict] = []
    clean_dicts: list[dict] = new
    if screen_fn is not None:
        with span("triage.screen") as step:
            # … existing screening body unchanged (from `logger.info("Screening %d emails…`
            #   through the quarantined_dicts storage loop), indented one level …
            step.set_attribute("rotom.triage.quarantined", len(quarantined_dicts))
            step.set_attribute("rotom.triage.deferred", len(screen.deferred))

    # 4. Classify (clean emails only)
    if not clean_dicts:
        logger.info("No clean emails to classify. Skipping.")
        return result

    with span("triage.classify", attributes={"rotom.triage.emails": len(clean_dicts)}):
        logger.info("Classifying %d clean emails", len(clean_dicts))
        try:
            classified = classify_fn(clean_dicts)
        except Exception as exc:  # noqa: BLE001 — degraded-state: don't hard-fail the run
            logger.exception("Classification failed; leaving %d emails for the next run", len(clean_dicts))
            result.errors["classify"] = f"classification failed: {exc}"
            return result
        logger.info("Classification complete")

    # 5a. Draft bodies BEFORE the write transaction (LLM I/O never inside a held SQLite write lock).
    draft_bodies: dict[str, str] = {}
    with span("triage.draft") as step:
        for e in classified:
            if e["category"] == Category.NEEDS_REPLY:
                try:
                    logger.info("Auto-drafting reply for needs_reply email: %s", e["message_id"])
                    draft_bodies[e["message_id"]] = draft_fn(e)
                except Exception as exc:  # noqa: BLE001 — degrade, never lose the email
                    logger.exception("Auto-draft failed for %s", e["message_id"])
                    result.errors[f"draft:{e['message_id']}"] = f"draft failed: {exc}"
        step.set_attribute("rotom.triage.drafts", len(draft_bodies))

    # 5b. Store emails + drafts + mark processed (per-message savepoints, see above).
    with span("triage.store") as step:
        # … existing storage loop unchanged, indented one level …
        step.set_attribute("rotom.triage.stored", len(result.new_emails))

    return result
```

Keep every original comment and statement; only indentation changes inside the new `with` blocks. Note `gmail.fetch` errors: the exception propagates out of the inner `with span(...)` (marking it ERROR) and is then caught by the existing `except` — that ordering is intentional.

- [ ] **Step 6: Run all backend tests**

Run: `cd api && uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add api/app/agent/graph.py api/app/agent/toolkit.py api/app/tools/gmail/pipeline.py \
  api/tests/test_agent_tracing.py api/tests/test_pipeline.py
git commit -m "feat(obs): spans for chat turns, agent tool calls and triage steps"
```

---

### Task 5: HTTP spans + opt-in Prometheus `/metrics`

**Files:**
- Create: `api/app/observability/metrics.py`, `api/app/observability/http.py`, `api/tests/test_metrics_http.py`
- Modify: `api/app/api/routes.py`, `api/app/observability/tracing.py`, `api/app/logging_setup.py`, `api/app/config.py`, `api/pyproject.toml`, `.env.example`

**Interfaces:**
- Consumes: `semconv`, `tracing.get_tracer`.
- Produces: setting `metrics_enabled: bool = False`; `metrics.REGISTRY`, `MetricsSpanProcessor`, `LogCountHandler`, `observe_http(method, route, status_code, seconds)`, `render() -> tuple[bytes, str]`; `http.install_http_observability(app)`; route `GET /metrics` (bearer auth; 404 when disabled). SERVER spans named `"{METHOD} {route template}"` for POST/PUT/PATCH/DELETE only.

- [ ] **Step 1: Dependency + setting**

Run: `cd api && uv add "prometheus-client>=0.26"`

`api/app/config.py` (Observability section): `metrics_enabled: bool = False  # expose Prometheus /metrics (bearer auth)`.
`.env.example` (Observability section): `METRICS_ENABLED=false      # true → GET /metrics (Prometheus text; same bearer API_TOKEN)`.

- [ ] **Step 2: Write the failing tests** — create `api/tests/test_metrics_http.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_metrics_http.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.observability.metrics'`.

- [ ] **Step 4: Create `api/app/observability/metrics.py`**

```python
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
```

- [ ] **Step 5: Create `api/app/observability/http.py`**

```python
"""API request observability. Every request feeds HTTP metrics (when enabled); only
mutating requests become SERVER spans — the dashboard's GET polling would otherwise
drown the trace list. Spans are named by route template (low cardinality)."""

import time
from contextlib import nullcontext

from fastapi import FastAPI, Request
from opentelemetry.trace import SpanKind, Status, StatusCode

from app.observability import semconv as sc

TRACED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_UNOBSERVED_PATHS = frozenset({"/metrics"})


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", None) or request.url.path


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
```

- [ ] **Step 6: Wire it up**
- `api/app/api/routes.py`: at the top of `create_app`, right after `app = FastAPI(title="rotom api")`:

```python
    from app.observability.http import install_http_observability

    install_http_observability(app)
```

and register (next to `/api/health`):

```python
    @app.get("/metrics", dependencies=[Depends(require_auth)], include_in_schema=False)
    def metrics_endpoint():
        from fastapi import Response

        from app.config import get_settings
        from app.observability import metrics

        if not get_settings().metrics_enabled:
            raise HTTPException(404, "Metrics disabled (set METRICS_ENABLED=true)")
        body, content_type = metrics.render()
        return Response(content=body, media_type=content_type)
```

- `api/app/observability/tracing.py` `init_tracing`: before `_provider = provider` add

```python
    from app.config import get_settings

    if get_settings().metrics_enabled:
        from app.observability.metrics import MetricsSpanProcessor

        provider.add_span_processor(MetricsSpanProcessor())
```

- `api/app/logging_setup.py` `setup_logging`: at the end add

```python
    from app.config import get_settings

    if get_settings().metrics_enabled:
        from app.observability.metrics import LogCountHandler

        root.addHandler(LogCountHandler())
```

- [ ] **Step 7: Run all backend tests**

Run: `cd api && uv run pytest -q`
Expected: PASS. (If `test_mutating_request_*` shows `name == "POST /api/drafts/1/discard"`, the route isn't in `request.scope` after `call_next` in this Starlette version — read `scope["route"]` from a scope captured by a pure ASGI middleware instead; the test pins the behavior.)

- [ ] **Step 8: Commit**

```bash
git add api/app/observability/metrics.py api/app/observability/http.py api/app/api/routes.py \
  api/app/observability/tracing.py api/app/logging_setup.py api/app/config.py \
  api/pyproject.toml api/uv.lock .env.example api/tests/test_metrics_http.py
git commit -m "feat(obs): HTTP server spans and opt-in Prometheus /metrics derived from spans"
```

---

### Task 6: SQL views, dashboard queries, read API, retention

**Files:**
- Create: `api/app/observability/queries.py`, `api/tests/test_obs_queries.py`
- Modify: `api/app/store/observability.py`, `api/app/api/routes.py`, `api/app/scheduler/jobs.py`, `api/app/config.py`, `.env.example`, `api/tests/test_observability_logs.py`

**Interfaces:**
- Consumes: `Span`, `RunLog`, `LogEntry`, `get_obs_session`.
- Produces (JSON shapes the web relies on — exact keys):
  - `queries.overview(hours, *, now=None)` → `{window_hours, bucket: "hour"|"day", buckets: [iso], kpis: {runs, runs_ok, problems, running, llm_calls, llm_errors, cost_usd, input_tokens, output_tokens, llm_p95_ms, error_logs}, runs_series: [{bucket, success, failure, degraded, interrupted, running}], cost_series: [{bucket, model, cost_usd, tokens}], jobs: [{kind, runs, success, problems, p50_ms, p95_ms, avg_cost_usd, last_run_id, last_status, last_started_at, last_summary}], problems: [{type:"run", ts, run_id, kind, status, summary, error, trace_id} | {type:"log", ts, id, logger, msg, run_id, trace_id}]}`
  - `queries.traces(*, limit=50, before=None, trace_type=None, status=None, q=None)` → `{traces: [{trace_id, root_span_id, root_name, trace_type, start_time, duration_ms, run_id, run_status, status, span_count, llm_calls, input_tokens, output_tokens, cost_usd, error_count}], next_before}`
  - `queries.trace_detail(trace_id)` → `{trace_id, spans: [span dict: all `span` columns, `attributes` dict, `events` list, times iso], logs: [{id, ts, level, logger, msg, run_id, kind, trace_id, span_id, exc_info, extra}], run: {id, kind, source, status, started_at, finished_at, summary, error} | null}` or `None`
  - `queries.llm_stats(days, *, now=None)` → `{days, buckets: [iso], kpis: {calls, errors, input_tokens, output_tokens, cache_read_tokens, reasoning_tokens, cost_usd, p50_ms, p95_ms, cache_hit_pct}, by_model: [{model, provider, …group stats}], by_role: [{role, …group stats}], daily: [{bucket, model, cost_usd, tokens}], recent: [{span_id, trace_id, run_id, run_kind, start_time, duration_ms, status, provider, model, role, input_tokens, output_tokens, cache_read_tokens, reasoning_tokens, cost_usd}]}`
  - Routes: `GET /api/observability/overview?hours=24`, `/traces?limit&before&type&status&q`, `/traces/{trace_id}`, `/llm?days=7` (all sync `def`); existing `/runs`, `/runs/{id}`, `/logs` converted to `def`.
  - Views: `v_runs`, `v_traces`, `v_llm_calls`, `v_tool_calls`, `v_errors`. Setting `trace_retention_days: int = 30`; `store.observability.prune_observability()`; scheduler job id `obs-prune`.

- [ ] **Step 1: Setting** — `api/app/config.py` Observability section: `trace_retention_days: int = 30  # span rows older than this are pruned (0 = keep all)`. Update the comment on `log_retention_days` to "pruned at startup and daily". `.env.example` Observability section: `TRACE_RETENTION_DAYS=30       # span rows (traces) older than this are pruned (0 = keep all)`.

- [ ] **Step 2: Write the failing tests** — create `api/tests/test_obs_queries.py`:

```python
"""Dashboard read models, SQL views, read API, retention."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from sqlalchemy import text

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _llm_call(cb, *, inp=100, out=10, model="gemini-2.5-flash", fail=False):
    rid = uuid.uuid4()
    cb.on_chat_model_start({}, [[HumanMessage("x")]], run_id=rid)
    if fail:
        cb.on_llm_error(TimeoutError("t"), run_id=rid)
        return
    msg = AIMessage(content="y", usage_metadata={"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out},
                    response_metadata={"model_name": model})
    cb.on_llm_end(LLMResult(generations=[[ChatGeneration(message=msg)]]), run_id=rid)


@pytest.fixture()
def seeded(traced):
    from app.observability.llm_tracing import LlmTracingCallback
    from app.observability.sink import record_run
    from app.observability.tracing import span

    cb = LlmTracingCallback("gemini", "gemini-2.5-flash", "classify")
    with record_run("gmail_triage", source="scheduler") as ok:
        with span("triage.classify"):
            _llm_call(cb)
            _llm_call(cb, fail=True)
    with record_run("gmail_triage", source="manual") as bad:
        bad.fail(summary="all accounts failed", error="quota")
    with record_run("reminder_fire", source="scheduler") as deg:
        deg.degrade(summary="not delivered")
    return {"ok": ok.run_id, "bad": bad.run_id, "deg": deg.run_id}


def test_overview_kpis_series_jobs_problems(seeded):
    from app.observability import queries

    o = queries.overview(24)
    k = o["kpis"]
    assert (k["runs"], k["runs_ok"], k["problems"]) == (3, 1, 2)
    assert (k["llm_calls"], k["llm_errors"]) == (2, 1)
    assert k["cost_usd"] > 0
    assert o["bucket"] == "hour" and len(o["buckets"]) in (24, 25)
    assert sum(b["success"] + b["failure"] + b["degraded"] for b in o["runs_series"]) == 3
    jobs = {j["kind"]: j for j in o["jobs"]}
    assert jobs["gmail_triage"]["runs"] == 2 and jobs["gmail_triage"]["problems"] == 1
    assert jobs["gmail_triage"]["last_status"] == "failure"
    assert {p["status"] for p in o["problems"] if p["type"] == "run"} == {"failure", "degraded"}
    assert all(p["trace_id"] for p in o["problems"] if p["type"] == "run")


def test_overview_day_buckets_for_long_windows(seeded):
    from app.observability import queries

    o = queries.overview(24 * 7)
    assert o["bucket"] == "day" and len(o["buckets"]) in (7, 8)


def test_traces_list_types_status_and_aggregates(seeded):
    from app.observability import queries

    res = queries.traces()
    assert len(res["traces"]) == 3
    first_ok = [t for t in res["traces"] if t["run_id"] == int(seeded["ok"])][0]
    assert first_ok["trace_type"] == "run"
    assert first_ok["llm_calls"] == 2
    assert first_ok["error_count"] == 1
    assert first_ok["run_status"] == "success"
    errors = queries.traces(status="error")["traces"]
    assert [t["run_id"] for t in errors] == [int(seeded["bad"])]
    assert queries.traces(trace_type="chat")["traces"] == []
    page = queries.traces(limit=2)
    assert len(page["traces"]) == 2 and page["next_before"]
    rest = queries.traces(limit=2, before=page["next_before"])["traces"]
    assert len(rest) == 1


def test_trace_detail_spans_logs_run(seeded):
    from app.observability import queries
    from app.store.observability import LogEntry, get_obs_session

    t = [x for x in queries.traces()["traces"] if x["run_id"] == int(seeded["ok"])][0]
    with get_obs_session() as s:
        s.add(LogEntry(ts=datetime.now(timezone.utc), level="INFO", logger="t", msg="hi", trace_id=t["trace_id"]))
        s.commit()
    d = queries.trace_detail(t["trace_id"])
    names = [sp["name"] for sp in d["spans"]]
    assert names[0] == "gmail_triage"
    assert "triage.classify" in names
    chat = [sp for sp in d["spans"] if sp["operation"] == "chat"][0]
    assert isinstance(chat["attributes"], dict)
    assert d["logs"][0]["msg"] == "hi"
    assert d["run"]["id"] == int(seeded["ok"])
    assert queries.trace_detail("f" * 32) is None


def test_trace_detail_with_orphan_spans(traced):
    from app.observability import queries
    from app.store.observability import Span, get_obs_session

    now = datetime.now(timezone.utc)
    with get_obs_session() as s:
        s.add(Span(span_id="c" * 16, trace_id="e" * 32, parent_span_id="d" * 16, name="child",
                   start_time=now, end_time=now, duration_ms=1.0))
        s.commit()
    d = queries.trace_detail("e" * 32)
    assert [sp["name"] for sp in d["spans"]] == ["child"]
    assert queries.traces()["traces"] == []  # no root yet → not listed


def test_llm_stats_groups_and_percentiles(seeded):
    from app.observability import queries

    st = queries.llm_stats(7)
    assert st["kpis"]["calls"] == 2 and st["kpis"]["errors"] == 1
    (m,) = st["by_model"]
    assert m["model"] == "gemini-2.5-flash" and m["calls"] == 2 and m["errors"] == 1
    (r,) = st["by_role"]
    assert r["role"] == "classify"
    assert st["recent"][0]["run_kind"] == "gmail_triage"
    assert st["kpis"]["p95_ms"] is not None


def test_views_are_queryable(seeded):
    from app.store.observability import get_obs_session

    with get_obs_session() as s:
        runs = s.execute(text("SELECT kind, llm_calls, cost_usd FROM v_runs ORDER BY run_id")).all()
        assert runs[0][1] == 2 and runs[0][2] > 0
        assert s.execute(text("SELECT COUNT(*) FROM v_traces")).scalar_one() == 3
        assert s.execute(text("SELECT COUNT(*) FROM v_llm_calls WHERE role = 'classify'")).scalar_one() == 2
        assert s.execute(text("SELECT COUNT(*) FROM v_errors WHERE source = 'span'")).scalar_one() >= 2
        s.execute(text("SELECT * FROM v_tool_calls")).all()


def test_prune_removes_old_logs_and_spans(obs_db, monkeypatch):
    from app.config import get_settings
    from app.store.observability import LogEntry, Span, get_obs_session, prune_observability

    old = datetime.now(timezone.utc) - timedelta(days=60)
    now = datetime.now(timezone.utc)
    with get_obs_session() as s:
        s.add(LogEntry(ts=old, level="INFO", logger="t", msg="old"))
        s.add(LogEntry(ts=now, level="INFO", logger="t", msg="new"))
        s.add(Span(span_id="1" * 16, trace_id="1" * 32, name="old", start_time=old, end_time=old, duration_ms=0))
        s.add(Span(span_id="2" * 16, trace_id="2" * 32, name="new", start_time=now, end_time=now, duration_ms=0))
        s.commit()
    monkeypatch.setattr(get_settings(), "log_retention_days", 14)
    monkeypatch.setattr(get_settings(), "trace_retention_days", 30)
    prune_observability()
    with get_obs_session() as s:
        assert [r.msg for r in s.query(LogEntry).all()] == ["new"]
        assert [r.name for r in s.query(Span).all()] == ["new"]


def test_prune_same_day_cutoff_is_exact(obs_db):
    """v1 compared ISO 'T' strings against space-separated stored values."""
    from app.store.observability import LogEntry, _prune_old_logs, get_obs_session

    now = datetime.now(timezone.utc)
    with get_obs_session() as s:
        s.add(LogEntry(ts=now - timedelta(days=1, minutes=1), level="INFO", logger="t", msg="older"))
        s.add(LogEntry(ts=now - timedelta(days=1) + timedelta(minutes=1), level="INFO", logger="t", msg="newer"))
        s.commit()
    from app.store import observability as obs

    _prune_old_logs(obs._engine, retention_days=1)
    with get_obs_session() as s:
        assert [r.msg for r in s.query(LogEntry).all()] == ["newer"]


@pytest.fixture()
def api(session_db, seeded):
    from app.api.routes import create_app

    return TestClient(create_app(api_token=TOKEN))


def test_read_api_endpoints(api, seeded):
    o = api.get("/api/observability/overview?hours=24", headers=AUTH).json()
    assert o["kpis"]["runs"] == 3
    t = api.get("/api/observability/traces?limit=10", headers=AUTH).json()
    assert len(t["traces"]) == 3
    tid = t["traces"][0]["trace_id"]
    assert api.get(f"/api/observability/traces/{tid}", headers=AUTH).json()["trace_id"] == tid
    assert api.get("/api/observability/traces/" + "0" * 32, headers=AUTH).status_code == 404
    assert api.get("/api/observability/llm?days=7", headers=AUTH).json()["kpis"]["calls"] == 2
    assert api.get("/api/observability/overview").status_code == 401
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_obs_queries.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.observability.queries'`.

- [ ] **Step 4: Views + retention** in `api/app/store/observability.py`

Add the view DDL and builder, and call `_create_views(conn)` as the last statement inside `_migrate`'s `with engine.begin()` block:

```python
# The SQL query surface (see docs/observability/QUERIES.md). Recreated on every startup
# so definition changes ship with the code.
_VIEWS = {
    "v_runs": """
        SELECT r.id AS run_id, r.kind, r.source, r.status, r.started_at, r.finished_at,
               (julianday(r.finished_at) - julianday(r.started_at)) * 86400000.0 AS duration_ms,
               r.summary, r.error, r.trace_id, r.parent_run_id,
               COALESCE(u.llm_calls, 0) AS llm_calls,
               COALESCE(u.input_tokens, 0) AS input_tokens,
               COALESCE(u.output_tokens, 0) AS output_tokens,
               u.cost_usd, COALESCE(u.error_spans, 0) AS error_spans
        FROM run_log r
        LEFT JOIN (
            SELECT run_id, SUM(operation = 'chat') AS llm_calls, SUM(input_tokens) AS input_tokens,
                   SUM(output_tokens) AS output_tokens, SUM(cost_usd) AS cost_usd,
                   SUM(status = 'ERROR') AS error_spans
            FROM span WHERE run_id IS NOT NULL GROUP BY run_id
        ) u ON u.run_id = r.id""",
    "v_traces": """
        SELECT root.trace_id, root.span_id AS root_span_id, root.name AS root_name,
               CASE WHEN json_extract(root.attributes, '$."rotom.run.kind"') IS NOT NULL THEN 'run'
                    WHEN root.operation = 'invoke_agent' THEN 'chat'
                    WHEN root.span_kind = 'SERVER' THEN 'http' ELSE 'other' END AS trace_type,
               root.start_time, root.duration_ms, root.run_id, root.status,
               json_extract(root.attributes, '$."rotom.run.status"') AS run_status,
               agg.span_count, agg.llm_calls, agg.input_tokens, agg.output_tokens,
               agg.cost_usd, agg.error_count
        FROM span root
        JOIN (
            SELECT trace_id, COUNT(*) AS span_count, SUM(operation = 'chat') AS llm_calls,
                   COALESCE(SUM(input_tokens), 0) AS input_tokens,
                   COALESCE(SUM(output_tokens), 0) AS output_tokens,
                   SUM(cost_usd) AS cost_usd, SUM(status = 'ERROR') AS error_count
            FROM span WHERE trace_id IS NOT NULL GROUP BY trace_id
        ) agg ON agg.trace_id = root.trace_id
        WHERE root.parent_span_id IS NULL AND root.trace_id IS NOT NULL""",
    "v_llm_calls": """
        SELECT s.span_id, s.trace_id, s.parent_span_id, s.run_id, r.kind AS run_kind,
               s.start_time, s.duration_ms, s.status, s.status_message, s.provider, s.model,
               json_extract(s.attributes, '$."rotom.llm.role"') AS role,
               s.input_tokens, s.output_tokens, s.cache_read_tokens, s.reasoning_tokens, s.cost_usd,
               json_extract(s.attributes, '$."gen_ai.response.finish_reasons"') AS finish_reasons,
               json_extract(s.attributes, '$."gen_ai.input.messages"') AS input_messages,
               json_extract(s.attributes, '$."gen_ai.output.messages"') AS output_messages
        FROM span s LEFT JOIN run_log r ON r.id = s.run_id
        WHERE s.operation = 'chat'""",
    "v_tool_calls": """
        SELECT s.span_id, s.trace_id, s.parent_span_id, s.run_id, s.start_time, s.duration_ms, s.status,
               json_extract(s.attributes, '$."gen_ai.tool.name"') AS tool,
               json_extract(s.attributes, '$."gen_ai.tool.call.arguments"') AS arguments,
               json_extract(s.attributes, '$."gen_ai.tool.call.result"') AS result
        FROM span s WHERE s.operation = 'execute_tool'""",
    "v_errors": """
        SELECT 'span' AS source, s.start_time AS ts, s.trace_id, s.span_id, s.run_id,
               s.name AS what, s.status_message AS message
        FROM span s WHERE s.status = 'ERROR'
        UNION ALL
        SELECT 'log', l.ts, l.trace_id, l.span_id, l.run_id, l.logger,
               l.msg || COALESCE(char(10) || l.exc_info, '')
        FROM log_entry l WHERE l.level IN ('ERROR', 'CRITICAL')""",
}


def _create_views(conn) -> None:
    from sqlalchemy import text

    for name, select_sql in _VIEWS.items():
        conn.execute(text(f"DROP VIEW IF EXISTS {name}"))
        conn.execute(text(f"CREATE VIEW {name} AS {select_sql}"))
```

Replace `_prune_old_logs` and add span pruning + the public entry point (typed deletes — SQLAlchemy serializes the cutoff in the same format it stored the rows):

```python
def _prune_old_logs(engine, retention_days: int) -> None:
    """Delete LogEntry rows older than retention_days (0 = keep everything)."""
    _prune(engine, LogEntry, LogEntry.ts, retention_days)


def _prune_old_spans(engine, retention_days: int) -> None:
    """Delete span rows older than retention_days (0 = keep everything)."""
    _prune(engine, Span, Span.end_time, retention_days)


def _prune(engine, model, column, retention_days: int) -> None:
    from datetime import timedelta

    from sqlalchemy import delete
    from sqlalchemy.orm import Session

    if retention_days <= 0:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    with Session(engine) as session:
        session.execute(delete(model).where(column < cutoff))
        session.commit()


def prune_observability() -> None:
    """Apply LOG_RETENTION_DAYS / TRACE_RETENTION_DAYS (startup + daily job)."""
    if _engine is None:
        create_all()
    settings = get_settings()
    _prune_old_logs(_engine, settings.log_retention_days)
    _prune_old_spans(_engine, settings.trace_retention_days)
```

In `create_all()`, replace `_prune_old_logs(_engine, settings.log_retention_days)` with:

```python
        _prune_old_logs(_engine, settings.log_retention_days)
        _prune_old_spans(_engine, settings.trace_retention_days)
```

- [ ] **Step 5: Create `api/app/observability/queries.py`**

```python
"""Dashboard read models over observability.db.

Plain SQL, SQLite-specific by design (SQL-first is the point — the same tables/views are
what you query by hand). Every function returns JSON-ready dicts; timestamps are ISO-8601
UTC with offset. Percentiles are computed in Python: SQLite has no percentile function
and single-user volumes are small.
"""

import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import text

from app.store.observability import get_obs_session

PROBLEM_STATUSES = ("failure", "degraded", "interrupted")
RUN_STATUSES = ("success", "failure", "degraded", "interrupted", "running")

_TRACE_TYPE_SQL = (
    "CASE WHEN json_extract(attributes, '$.\"rotom.run.kind\"') IS NOT NULL THEN 'run' "
    "WHEN operation = 'invoke_agent' THEN 'chat' "
    "WHEN span_kind = 'SERVER' THEN 'http' ELSE 'other' END"
)


# --- helpers -----------------------------------------------------------------

def _utc(value: Any) -> datetime | None:
    if value is None:
        return None
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(value: Any) -> str | None:
    dt = _utc(value)
    return dt.isoformat() if dt else None


def _db_ts(dt: datetime) -> str:
    """A UTC datetime in the exact text format SQLAlchemy stores (string-comparable)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


def _floor(dt: datetime, bucket: str) -> datetime:
    dt = dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return dt.replace(hour=0) if bucket == "day" else dt


def _buckets(since: datetime, now: datetime, bucket: str) -> list[datetime]:
    step = timedelta(days=1) if bucket == "day" else timedelta(hours=1)
    out, cur = [], _floor(since, bucket)
    while cur <= now:
        out.append(cur)
        cur += step
    return out


def _pct(values: Iterable[float], p: float) -> float | None:
    """Nearest-rank percentile."""
    ordered = sorted(v for v in values if v is not None)
    if not ordered:
        return None
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return round(ordered[rank - 1], 1)


def _json(raw: str | None, default: Any) -> Any:
    try:
        return json.loads(raw) if raw else default
    except ValueError:
        return default


def _sum_cost(values: Iterable[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals), 6) if vals else None


# --- overview ----------------------------------------------------------------

def overview(hours: int, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    bucket = "hour" if hours <= 48 else "day"
    params = {"since": _db_ts(since)}
    with get_obs_session() as s:
        runs = s.execute(text(
            "SELECT id, kind, source, status, started_at, finished_at, summary, error, trace_id "
            "FROM run_log WHERE started_at >= :since ORDER BY id DESC"), params).mappings().all()
        llm = s.execute(text(
            "SELECT model, duration_ms, status, input_tokens, output_tokens, cost_usd, start_time "
            "FROM span WHERE operation = 'chat' AND start_time >= :since"), params).mappings().all()
        error_logs = s.execute(text(
            "SELECT COUNT(*) FROM log_entry WHERE level IN ('ERROR', 'CRITICAL') AND ts >= :since"),
            params).scalar_one()
        recent_errors = s.execute(text(
            "SELECT id, ts, logger, msg, run_id, trace_id FROM log_entry "
            "WHERE level IN ('ERROR', 'CRITICAL') AND ts >= :since ORDER BY id DESC LIMIT 10"),
            params).mappings().all()
        last_by_kind = s.execute(text(
            "SELECT r.kind, r.id, r.status, r.started_at, r.summary FROM run_log r "
            "JOIN (SELECT kind, MAX(id) AS id FROM run_log GROUP BY kind) m ON m.id = r.id")).mappings().all()
        run_cost = dict(s.execute(text(
            "SELECT run_id, SUM(cost_usd) FROM span WHERE run_id IS NOT NULL AND operation = 'chat' "
            "AND start_time >= :since GROUP BY run_id"), params).all())

    bucket_list = _buckets(since, now, bucket)
    series = {b: {"bucket": b.isoformat(), **{st: 0 for st in RUN_STATUSES}} for b in bucket_list}
    for r in runs:
        key = _floor(_utc(r["started_at"]), bucket)
        if key in series and r["status"] in RUN_STATUSES:
            series[key][r["status"]] += 1

    cost: dict[tuple[datetime, str], dict[str, float]] = defaultdict(lambda: {"cost_usd": 0.0, "tokens": 0})
    for c in llm:
        key = (_floor(_utc(c["start_time"]), bucket), c["model"] or "unknown")
        cost[key]["cost_usd"] += c["cost_usd"] or 0.0
        cost[key]["tokens"] += (c["input_tokens"] or 0) + (c["output_tokens"] or 0)
    cost_series = [
        {"bucket": b.isoformat(), "model": m, "cost_usd": round(v["cost_usd"], 6), "tokens": v["tokens"]}
        for (b, m), v in sorted(cost.items())
    ]

    by_kind: dict[str, list] = defaultdict(list)
    for r in runs:
        by_kind[r["kind"]].append(r)
    last = {r["kind"]: r for r in last_by_kind}
    jobs = []
    for kind in sorted(set(by_kind) | set(last)):
        rs = by_kind.get(kind, [])
        durations = [
            (_utc(r["finished_at"]) - _utc(r["started_at"])).total_seconds() * 1000
            for r in rs if r["finished_at"]
        ]
        costs = [run_cost[r["id"]] for r in rs if run_cost.get(r["id"]) is not None]
        lr = last.get(kind)
        jobs.append({
            "kind": kind,
            "runs": len(rs),
            "success": sum(r["status"] == "success" for r in rs),
            "problems": sum(r["status"] in PROBLEM_STATUSES for r in rs),
            "p50_ms": _pct(durations, 50),
            "p95_ms": _pct(durations, 95),
            "avg_cost_usd": round(sum(costs) / len(costs), 6) if costs else None,
            "last_run_id": lr["id"] if lr else None,
            "last_status": lr["status"] if lr else None,
            "last_started_at": _iso(lr["started_at"]) if lr else None,
            "last_summary": (lr["summary"] or "") if lr else "",
        })
    jobs.sort(key=lambda j: j["last_started_at"] or "", reverse=True)

    problems = [
        {"type": "run", "ts": _iso(r["started_at"]), "run_id": r["id"], "kind": r["kind"],
         "status": r["status"], "summary": r["summary"] or "", "error": r["error"] or "",
         "trace_id": r["trace_id"]}
        for r in runs if r["status"] in PROBLEM_STATUSES
    ][:10] + [
        {"type": "log", "ts": _iso(e["ts"]), "id": e["id"], "logger": e["logger"], "msg": e["msg"],
         "run_id": e["run_id"], "trace_id": e["trace_id"]}
        for e in recent_errors
    ]
    problems.sort(key=lambda p: p["ts"] or "", reverse=True)

    llm_durations = [c["duration_ms"] for c in llm]
    return {
        "window_hours": hours,
        "bucket": bucket,
        "buckets": [b.isoformat() for b in bucket_list],
        "kpis": {
            "runs": len(runs),
            "runs_ok": sum(r["status"] == "success" for r in runs),
            "problems": sum(r["status"] in PROBLEM_STATUSES for r in runs),
            "running": sum(r["status"] == "running" for r in runs),
            "llm_calls": len(llm),
            "llm_errors": sum(c["status"] == "ERROR" for c in llm),
            "cost_usd": round(sum(c["cost_usd"] or 0.0 for c in llm), 6),
            "input_tokens": sum(c["input_tokens"] or 0 for c in llm),
            "output_tokens": sum(c["output_tokens"] or 0 for c in llm),
            "llm_p95_ms": _pct(llm_durations, 95),
            "error_logs": error_logs,
        },
        "runs_series": list(series.values()),
        "cost_series": cost_series,
        "jobs": jobs,
        "problems": problems[:12],
    }


def empty_overview(hours: int) -> dict[str, Any]:
    return {"window_hours": hours, "bucket": "hour" if hours <= 48 else "day", "buckets": [],
            "kpis": {"runs": 0, "runs_ok": 0, "problems": 0, "running": 0, "llm_calls": 0,
                     "llm_errors": 0, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
                     "llm_p95_ms": None, "error_logs": 0},
            "runs_series": [], "cost_series": [], "jobs": [], "problems": []}


# --- traces ------------------------------------------------------------------

def traces(
    *,
    limit: int = 50,
    before: str | None = None,
    trace_type: str | None = None,
    status: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    where = ["parent_span_id IS NULL", "trace_id IS NOT NULL"]
    params: dict[str, Any] = {"limit": limit + 1}
    if before:
        where.append("start_time < :before")
        params["before"] = _db_ts(_utc(before))
    if trace_type:
        where.append(f"{_TRACE_TYPE_SQL} = :ttype")
        params["ttype"] = trace_type
    if status == "error":
        where.append("status = 'ERROR'")
    elif status == "ok":
        where.append("status != 'ERROR'")
    if q:
        where.append("name LIKE :q")
        params["q"] = f"%{q}%"
    with get_obs_session() as s:
        roots = s.execute(text(
            f"SELECT trace_id, span_id, name, {_TRACE_TYPE_SQL} AS trace_type, start_time, duration_ms, "
            "run_id, status, json_extract(attributes, '$.\"rotom.run.status\"') AS run_status "
            f"FROM span WHERE {' AND '.join(where)} ORDER BY start_time DESC LIMIT :limit"),
            params).mappings().all()
        has_more = len(roots) > limit
        roots = roots[:limit]
        agg: dict[str, Any] = {}
        if roots:
            ids = {f"t{i}": r["trace_id"] for i, r in enumerate(roots)}
            placeholders = ",".join(f":{k}" for k in ids)
            for a in s.execute(text(
                "SELECT trace_id, COUNT(*) AS span_count, SUM(operation = 'chat') AS llm_calls, "
                "COALESCE(SUM(input_tokens), 0) AS input_tokens, COALESCE(SUM(output_tokens), 0) AS output_tokens, "
                "SUM(cost_usd) AS cost_usd, SUM(status = 'ERROR') AS error_count "
                f"FROM span WHERE trace_id IN ({placeholders}) GROUP BY trace_id"), ids).mappings():
                agg[a["trace_id"]] = a
    out = []
    for r in roots:
        a = agg.get(r["trace_id"], {})
        out.append({
            "trace_id": r["trace_id"],
            "root_span_id": r["span_id"],
            "root_name": r["name"],
            "trace_type": r["trace_type"],
            "start_time": _iso(r["start_time"]),
            "duration_ms": r["duration_ms"],
            "run_id": r["run_id"],
            "run_status": r["run_status"],
            "status": r["status"],
            "span_count": a.get("span_count", 1),
            "llm_calls": a.get("llm_calls") or 0,
            "input_tokens": a.get("input_tokens", 0),
            "output_tokens": a.get("output_tokens", 0),
            "cost_usd": a.get("cost_usd"),
            "error_count": a.get("error_count") or 0,
        })
    return {"traces": out, "next_before": _iso(roots[-1]["start_time"]) if has_more and roots else None}


def _span_dict(r) -> dict[str, Any]:
    d = dict(r)
    d["start_time"] = _iso(d["start_time"])
    d["end_time"] = _iso(d["end_time"])
    d["attributes"] = _json(d.get("attributes"), {})
    d["events"] = _json(d.get("events"), [])
    return d


def _log_dict(r) -> dict[str, Any]:
    d = dict(r)
    d["ts"] = _iso(d["ts"])
    return d


def trace_detail(trace_id: str) -> dict[str, Any] | None:
    with get_obs_session() as s:
        spans = s.execute(text("SELECT * FROM span WHERE trace_id = :t ORDER BY start_time ASC"),
                          {"t": trace_id}).mappings().all()
        if not spans:
            return None
        logs = s.execute(text(
            "SELECT id, ts, level, logger, msg, run_id, kind, trace_id, span_id, exc_info, extra "
            "FROM log_entry WHERE trace_id = :t ORDER BY id ASC LIMIT 2000"), {"t": trace_id}).mappings().all()
        run = s.execute(text(
            "SELECT id, kind, source, status, started_at, finished_at, summary, error "
            "FROM run_log WHERE trace_id = :t ORDER BY id ASC LIMIT 1"), {"t": trace_id}).mappings().first()
    run_dict = None
    if run:
        run_dict = dict(run)
        run_dict["started_at"] = _iso(run_dict["started_at"])
        run_dict["finished_at"] = _iso(run_dict["finished_at"])
    return {"trace_id": trace_id, "spans": [_span_dict(r) for r in spans],
            "logs": [_log_dict(l) for l in logs], "run": run_dict}


# --- LLM ---------------------------------------------------------------------

def _group_stats(rows: list) -> dict[str, Any]:
    return {
        "calls": len(rows),
        "errors": sum(r["status"] == "ERROR" for r in rows),
        "input_tokens": sum(r["input_tokens"] for r in rows),
        "output_tokens": sum(r["output_tokens"] for r in rows),
        "cache_read_tokens": sum(r["cache_read_tokens"] for r in rows),
        "reasoning_tokens": sum(r["reasoning_tokens"] for r in rows),
        "cost_usd": _sum_cost(r["cost_usd"] for r in rows),
        "p50_ms": _pct((r["duration_ms"] for r in rows), 50),
        "p95_ms": _pct((r["duration_ms"] for r in rows), 95),
    }


def llm_stats(days: int, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    with get_obs_session() as s:
        rows = s.execute(text(
            "SELECT s.span_id, s.trace_id, s.run_id, r.kind AS run_kind, s.start_time, s.duration_ms, "
            "s.status, s.provider, s.model, json_extract(s.attributes, '$.\"rotom.llm.role\"') AS role, "
            "COALESCE(s.input_tokens, 0) AS input_tokens, COALESCE(s.output_tokens, 0) AS output_tokens, "
            "COALESCE(s.cache_read_tokens, 0) AS cache_read_tokens, "
            "COALESCE(s.reasoning_tokens, 0) AS reasoning_tokens, s.cost_usd "
            "FROM span s LEFT JOIN run_log r ON r.id = s.run_id "
            "WHERE s.operation = 'chat' AND s.start_time >= :since ORDER BY s.start_time DESC"),
            {"since": _db_ts(since)}).mappings().all()

    by_model: dict[tuple, list] = defaultdict(list)
    by_role: dict[str, list] = defaultdict(list)
    daily: dict[tuple, dict] = defaultdict(lambda: {"cost_usd": 0.0, "tokens": 0})
    for r in rows:
        by_model[(r["model"] or "unknown", r["provider"])].append(r)
        by_role[r["role"] or "unknown"].append(r)
        key = (_floor(_utc(r["start_time"]), "day"), r["model"] or "unknown")
        daily[key]["cost_usd"] += r["cost_usd"] or 0.0
        daily[key]["tokens"] += r["input_tokens"] + r["output_tokens"]

    kpis = _group_stats(rows)
    kpis["cache_hit_pct"] = (
        round(kpis["cache_read_tokens"] / kpis["input_tokens"] * 100, 1) if kpis["input_tokens"] else None
    )
    recent = []
    for r in rows[:50]:
        d = dict(r)
        d["start_time"] = _iso(d["start_time"])
        recent.append(d)
    return {
        "days": days,
        "buckets": [b.isoformat() for b in _buckets(since, now, "day")],
        "kpis": kpis,
        "by_model": sorted(
            ({"model": m, "provider": p, **_group_stats(rs)} for (m, p), rs in by_model.items()),
            key=lambda x: (x["cost_usd"] or 0, x["calls"]), reverse=True),
        "by_role": sorted(
            ({"role": role, **_group_stats(rs)} for role, rs in by_role.items()),
            key=lambda x: x["calls"], reverse=True),
        "daily": [{"bucket": b.isoformat(), "model": m, "cost_usd": round(v["cost_usd"], 6), "tokens": v["tokens"]}
                  for (b, m), v in sorted(daily.items())],
        "recent": recent,
    }


def empty_llm_stats(days: int) -> dict[str, Any]:
    zero = {"calls": 0, "errors": 0, "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
            "reasoning_tokens": 0, "cost_usd": None, "p50_ms": None, "p95_ms": None, "cache_hit_pct": None}
    return {"days": days, "buckets": [], "kpis": zero, "by_model": [], "by_role": [], "daily": [], "recent": []}
```

- [ ] **Step 6: Read API** — in `api/app/api/routes.py`, convert the four existing observability GET handlers from `async def` to `def` (bodies unchanged), then add after the logs route:

```python
    @app.get("/api/observability/overview", dependencies=[Depends(require_auth)])
    def get_obs_overview(hours: int = 24):
        from app.observability import queries

        hours = max(1, min(hours, 24 * 90))
        return _safe_obs_read(lambda: queries.overview(hours), queries.empty_overview(hours), "overview")

    @app.get("/api/observability/traces", dependencies=[Depends(require_auth)])
    def get_obs_traces(limit: int = 50, before: str = "", type: str = "", status: str = "", q: str = ""):
        from app.observability import queries

        return _safe_obs_read(
            lambda: queries.traces(limit=max(1, min(limit, 200)), before=before or None,
                                   trace_type=type or None, status=status or None, q=q or None),
            {"traces": [], "next_before": None}, "traces",
        )

    @app.get("/api/observability/traces/{trace_id}", dependencies=[Depends(require_auth)])
    def get_obs_trace(trace_id: str):
        from app.observability import queries

        detail = _safe_obs_read(lambda: queries.trace_detail(trace_id), None, "trace")
        if detail is None:
            raise HTTPException(status_code=404, detail="Trace not found")
        return detail

    @app.get("/api/observability/llm", dependencies=[Depends(require_auth)])
    def get_obs_llm(days: int = 7):
        from app.observability import queries

        days = max(1, min(days, 90))
        return _safe_obs_read(lambda: queries.llm_stats(days), queries.empty_llm_stats(days), "llm")
```

- [ ] **Step 7: Daily retention job** — in `api/app/scheduler/jobs.py` add:

```python
def prune_observability_job() -> None:
    """Apply log/trace retention daily (startup prunes too). Never raises."""
    try:
        from app.store.observability import prune_observability

        prune_observability()
    except Exception:
        logger.exception("Observability prune failed")
```

and in `create_scheduler()` before `_scheduler = scheduler`:

```python
    scheduler.add_job(
        prune_observability_job,
        CronTrigger(hour=4, minute=0, timezone=settings.timezone),
        id="obs-prune",
        replace_existing=True,
        misfire_grace_time=6 * 3600,
    )
```

- [ ] **Step 8: Old retention tests** — `api/tests/test_observability_logs.py::test_prune_old_logs` keeps working (`_prune_old_logs(_engine, retention_days=14)` signature unchanged). Leave it.

- [ ] **Step 9: Run all backend tests**

Run: `cd api && uv run pytest -q`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add api/app/observability/queries.py api/app/store/observability.py api/app/api/routes.py \
  api/app/scheduler/jobs.py api/app/config.py .env.example api/tests/test_obs_queries.py
git commit -m "feat(obs): SQL views, dashboard read models + API, daily log/trace retention"
```

---

### Task 7: Web — data layer, navigation, Overview dashboard

**Files:**
- Modify: `web/lib/api.ts`, `web/lib/nav.ts`, `web/lib/format/number.ts`, `web/app/observability/page.tsx` (rewrite)
- Create: `web/components/obs/kpi.tsx`, `web/components/obs/window-tabs.tsx`, `web/components/obs/runs-chart.tsx`, `web/components/obs/spend-chart.tsx`, `web/components/obs/job-health.tsx`, `web/components/obs/problems-list.tsx`
- Delete: `web/components/tokens-chart.tsx`, `web/lib/view/usage.ts`
- Backend: delete `GET /api/observability/usage` route (`api/app/api/routes.py`) and `SqliteSink.usage_by_model_day` + its Protocol entry (`sink.py`).

**Interfaces:**
- Consumes: the Task 6 JSON shapes.
- Produces: TS types + fetchers in `lib/api.ts` (names below, used by Tasks 8–9); `formatUsd(v)` and `formatMs(ms)` in `lib/format/number.ts`; `<Kpi>`, `<WindowTabs>`, `<SpendChart>` reused by Task 9.

- [ ] **Step 1: Read the Next 16 docs you need** — per `web/AGENTS.md`, skim `web/node_modules/next/dist/docs/` for `searchParams` in page props (it is a Promise in Next 15+/16) and dynamic route `params`. Load the `dataviz` and `frontend-design` skills.

- [ ] **Step 2: Types + fetchers** — in `web/lib/api.ts`:
- Add `trace_id: string | null;` to `RunLog`.
- Replace `RunDetail.metrics` item type with `{ model: string; calls: number; input_tokens: number; output_tokens: number; avg_latency_ms: number | null; cost_usd: number | null }`.
- Add `trace_id: string | null; span_id: string | null; exc_info: string | null;` to `LogEntry`; add `trace_id?: string;` to `LogsFilters` and `if (filters.trace_id) params.set("trace_id", filters.trace_id);` in `getLogs`.
- Delete `UsageAggregation` and `getUsage`.
- Append:

```ts
export type SpanStatus = "UNSET" | "OK" | "ERROR";

export interface SpanEvent {
  name: string;
  ts: string | null;
  attributes: Record<string, unknown>;
}

export interface SpanRow {
  span_id: string;
  trace_id: string | null;
  parent_span_id: string | null;
  name: string;
  span_kind: string;
  start_time: string;
  end_time: string;
  duration_ms: number;
  status: SpanStatus;
  status_message: string;
  run_id: number | null;
  operation: string | null;
  provider: string | null;
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cache_read_tokens: number | null;
  reasoning_tokens: number | null;
  cost_usd: number | null;
  attributes: Record<string, unknown>;
  events: SpanEvent[];
}

export interface TraceRunRef {
  id: number;
  kind: string;
  source: string;
  status: RunStatus;
  started_at: string | null;
  finished_at: string | null;
  summary: string;
  error: string;
}

export interface TraceDetail {
  trace_id: string;
  spans: SpanRow[];
  logs: LogEntry[];
  run: TraceRunRef | null;
}

export type TraceType = "run" | "chat" | "http" | "other";

export interface TraceSummary {
  trace_id: string;
  root_span_id: string;
  root_name: string;
  trace_type: TraceType;
  start_time: string;
  duration_ms: number;
  run_id: number | null;
  run_status: RunStatus | null;
  status: SpanStatus;
  span_count: number;
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
  error_count: number;
}

export interface TracesPage {
  traces: TraceSummary[];
  next_before: string | null;
}

export interface TracesFilters {
  type?: string;
  status?: string;
  q?: string;
  before?: string;
  limit?: number;
}

export interface CostPoint {
  bucket: string;
  model: string;
  cost_usd: number;
  tokens: number;
}

export interface RunsBucket {
  bucket: string;
  success: number;
  failure: number;
  degraded: number;
  interrupted: number;
  running: number;
}

export interface JobHealth {
  kind: string;
  runs: number;
  success: number;
  problems: number;
  p50_ms: number | null;
  p95_ms: number | null;
  avg_cost_usd: number | null;
  last_run_id: number | null;
  last_status: RunStatus | null;
  last_started_at: string | null;
  last_summary: string;
}

export type Problem =
  | { type: "run"; ts: string; run_id: number; kind: string; status: RunStatus; summary: string; error: string; trace_id: string | null }
  | { type: "log"; ts: string; id: number; logger: string; msg: string; run_id: number | null; trace_id: string | null };

export interface Overview {
  window_hours: number;
  bucket: "hour" | "day";
  buckets: string[];
  kpis: {
    runs: number;
    runs_ok: number;
    problems: number;
    running: number;
    llm_calls: number;
    llm_errors: number;
    cost_usd: number;
    input_tokens: number;
    output_tokens: number;
    llm_p95_ms: number | null;
    error_logs: number;
  };
  runs_series: RunsBucket[];
  cost_series: CostPoint[];
  jobs: JobHealth[];
  problems: Problem[];
}

export interface LlmGroupStats {
  calls: number;
  errors: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  reasoning_tokens: number;
  cost_usd: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
}

export interface LlmCall {
  span_id: string;
  trace_id: string | null;
  run_id: number | null;
  run_kind: string | null;
  start_time: string;
  duration_ms: number;
  status: SpanStatus;
  provider: string | null;
  model: string | null;
  role: string | null;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  reasoning_tokens: number;
  cost_usd: number | null;
}

export interface LlmStats {
  days: number;
  buckets: string[];
  kpis: LlmGroupStats & { cache_hit_pct: number | null };
  by_model: (LlmGroupStats & { model: string; provider: string | null })[];
  by_role: (LlmGroupStats & { role: string })[];
  daily: CostPoint[];
  recent: LlmCall[];
}

export const getOverview = (hours = 24) =>
  apiFetch<Overview>(`/api/observability/overview?hours=${hours}`);

export const getTraces = (f: TracesFilters = {}) => {
  const p = new URLSearchParams();
  if (f.type) p.set("type", f.type);
  if (f.status) p.set("status", f.status);
  if (f.q) p.set("q", f.q);
  if (f.before) p.set("before", f.before);
  if (f.limit != null) p.set("limit", String(f.limit));
  const qs = p.toString();
  return apiFetch<TracesPage>(`/api/observability/traces${qs ? `?${qs}` : ""}`);
};

export const getTrace = (traceId: string) =>
  apiFetch<TraceDetail>(`/api/observability/traces/${encodeURIComponent(traceId)}`);

export const getLlmStats = (days = 7) =>
  apiFetch<LlmStats>(`/api/observability/llm?days=${days}`);
```

- [ ] **Step 3: Formatters** — append to `web/lib/format/number.ts`:

```ts
/** USD with precision that scales down for tiny LLM costs: $0.0004, $0.012, $3.40. */
export function formatUsd(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v === 0) return "$0";
  if (v < 0.01) return `$${v.toFixed(4)}`;
  if (v < 1) return `$${v.toFixed(3)}`;
  return `$${v.toFixed(2)}`;
}

/** Span/LLM durations: "<1ms", "420ms", "3.21s", "1m 5s", "—". */
export function formatMs(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1) return "<1ms";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)}s`;
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`;
}
```

- [ ] **Step 4: Navigation** — in `web/lib/nav.ts` remove the `Runs` item from the Email section and set the Observability section to:

```ts
  {
    label: "Observability",
    items: [
      { title: "Overview", href: "/observability", icon: "Gauge" },
      { title: "Traces", href: "/observability/traces", icon: "Waypoints" },
      { title: "LLM", href: "/observability/llm", icon: "Sparkle" },
      { title: "Runs", href: "/email/runs", icon: "History" },
      { title: "Logs", href: "/observability/logs", icon: "ScrollText" },
    ],
  },
```

and in `DETAIL_BASES` change the runs entry's `section` to `"Observability"` and add, first in the list:

```ts
  { test: /^\/observability\/traces\/[^/]+$/, section: "Observability", leafHref: "/observability/traces", leafLabel: "Traces" },
```

Confirm each icon name exists in `components/ui/icon.tsx` (lucide export names); if one is missing there, use one that is (e.g. `Activity`).

- [ ] **Step 5: Shared obs components**

`web/components/obs/kpi.tsx`:

```tsx
import { Icon } from "@/components/ui/icon";
import { cn } from "@/lib/utils";

/** KPI tile: label, big value, one line of context. `tone` tints the value only. */
export function Kpi({
  label,
  value,
  sub,
  icon,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  icon: string;
  tone?: "danger" | "warning" | "success";
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Icon name={icon} size={14} /> {label}
      </div>
      <div
        className={cn(
          "mt-2 text-2xl font-semibold tabular-nums",
          tone === "danger" && "text-destructive",
          tone === "warning" && "text-warning",
          tone === "success" && "text-success",
        )}
      >
        {value}
      </div>
      {sub && <div className="mt-0.5 text-xs text-faint">{sub}</div>}
    </div>
  );
}
```

`web/components/obs/window-tabs.tsx`:

```tsx
import Link from "next/link";
import { cn } from "@/lib/utils";

/** Server-rendered segmented control that sets one search param. */
export function WindowTabs({
  param,
  value,
  options,
  basePath,
}: {
  param: string;
  value: string;
  options: { value: string; label: string }[];
  basePath: string;
}) {
  return (
    <div className="inline-flex rounded-md border border-border bg-card p-0.5 text-xs">
      {options.map((o) => (
        <Link
          key={o.value}
          href={`${basePath}?${param}=${o.value}`}
          className={cn(
            "rounded px-2.5 py-1 font-medium transition-colors",
            o.value === value ? "bg-brand-soft text-brand" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {o.label}
        </Link>
      ))}
    </div>
  );
}
```

`web/components/obs/runs-chart.tsx`:

```tsx
"use client";

import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import type { RunsBucket } from "@/lib/api";
import { normalizeTs } from "@/lib/obs-utils";

const SERIES: { key: keyof Omit<RunsBucket, "bucket">; label: string; color: string }[] = [
  { key: "success", label: "Success", color: "var(--success)" },
  { key: "degraded", label: "Degraded", color: "var(--warning)" },
  { key: "interrupted", label: "Interrupted", color: "var(--slate)" },
  { key: "failure", label: "Failed", color: "var(--destructive)" },
  { key: "running", label: "Running", color: "var(--brand)" },
];

export function bucketLabel(iso: string, bucket: "hour" | "day"): string {
  const d = new Date(normalizeTs(iso));
  return bucket === "hour"
    ? d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false })
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function RunsChart({ series, bucket }: { series: RunsBucket[]; bucket: "hour" | "day" }) {
  if (!series.some((b) => SERIES.some((s) => b[s.key] > 0))) {
    return <div className="flex h-56 items-center justify-center text-sm text-muted-foreground">No runs in this window.</div>;
  }
  const config: ChartConfig = Object.fromEntries(SERIES.map((s) => [s.key, { label: s.label, color: s.color }]));
  const data = series.map((b) => ({ ...b, label: bucketLabel(b.bucket, bucket) }));
  return (
    <ChartContainer config={config} className="h-56 w-full">
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 11 }} minTickGap={16} />
        <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fontSize: 11 }} width={28} />
        <ChartTooltip content={<ChartTooltipContent indicator="dot" />} />
        <ChartLegend content={<ChartLegendContent />} />
        {SERIES.map((s, i) => (
          <Bar key={s.key} dataKey={s.key} stackId="runs" fill={s.color}
               radius={i === SERIES.length - 1 ? [3, 3, 0, 0] : [0, 0, 0, 0]} />
        ))}
      </BarChart>
    </ChartContainer>
  );
}
```

`web/components/obs/spend-chart.tsx`:

```tsx
"use client";

import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import type { CostPoint } from "@/lib/api";
import { formatUsd } from "@/lib/format/number";
import { bucketLabel } from "@/components/obs/runs-chart";

const PALETTE = ["var(--brand)", "var(--slate)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)", "var(--success)"];

/** Stacked spend per bucket by model. `buckets` fixes the x-axis (empty buckets show as gaps). */
export function SpendChart({
  points,
  buckets,
  bucket,
}: {
  points: CostPoint[];
  buckets: string[];
  bucket: "hour" | "day";
}) {
  const models = Array.from(new Set(points.map((p) => p.model))).sort();
  if (models.length === 0) {
    return <div className="flex h-56 items-center justify-center text-sm text-muted-foreground">No LLM calls in this window.</div>;
  }
  const byBucket = new Map<string, Record<string, number>>();
  for (const p of points) {
    const row = byBucket.get(p.bucket) ?? {};
    row[p.model] = (row[p.model] ?? 0) + p.cost_usd;
    byBucket.set(p.bucket, row);
  }
  const data = buckets.map((b) => ({ label: bucketLabel(b, bucket), ...(byBucket.get(b) ?? {}) }));
  const config: ChartConfig = Object.fromEntries(
    models.map((m, i) => [m, { label: m, color: PALETTE[i % PALETTE.length] }]),
  );
  return (
    <ChartContainer config={config} className="h-56 w-full">
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 11 }} minTickGap={16} />
        <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11 }} width={52}
               tickFormatter={(v: number) => formatUsd(v)} />
        <ChartTooltip content={<ChartTooltipContent indicator="dot"
          formatter={(value, name) => (
            <span className="flex w-full justify-between gap-3">
              <span className="text-muted-foreground">{String(name)}</span>
              <span className="font-mono tabular-nums">{formatUsd(Number(value))}</span>
            </span>
          )} />} />
        <ChartLegend content={<ChartLegendContent />} />
        {models.map((m, i) => (
          <Bar key={m} dataKey={m} stackId="cost" fill={PALETTE[i % PALETTE.length]}
               radius={i === models.length - 1 ? [3, 3, 0, 0] : [0, 0, 0, 0]} />
        ))}
      </BarChart>
    </ChartContainer>
  );
}
```

`web/components/obs/job-health.tsx`:

```tsx
import Link from "next/link";
import type { JobHealth, RunStatus } from "@/lib/api";
import { RUN_STATUS } from "@/lib/view/run";
import { toneDot } from "@/lib/tone";
import { relativeTime } from "@/lib/format/datetime";
import { formatMs, formatUsd } from "@/lib/format/number";
import { normalizeTs } from "@/lib/obs-utils";

export function JobHealthTable({ jobs }: { jobs: JobHealth[] }) {
  if (jobs.length === 0) {
    return <p className="px-4 py-8 text-center text-sm text-muted-foreground">No runs recorded yet.</p>;
  }
  const now = Date.now();
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-border text-xs tracking-wider text-muted-foreground uppercase">
          <tr>
            <th className="px-4 py-2 font-medium">Job</th>
            <th className="px-4 py-2 font-medium">Last run</th>
            <th className="px-4 py-2 text-right font-medium">Runs</th>
            <th className="px-4 py-2 text-right font-medium">Success</th>
            <th className="px-4 py-2 text-right font-medium">p50 / p95</th>
            <th className="px-4 py-2 text-right font-medium">Avg cost</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {jobs.map((j) => {
            const st = j.last_status ? RUN_STATUS[j.last_status as RunStatus] : null;
            const rate = j.runs ? Math.round((j.success / j.runs) * 100) : null;
            return (
              <tr key={j.kind} className="hover:bg-accent/40">
                <td className="px-4 py-2 font-medium">
                  <Link href={`/email/runs?kind=${encodeURIComponent(j.kind)}`} className="hover:underline">{j.kind}</Link>
                </td>
                <td className="px-4 py-2">
                  {j.last_run_id ? (
                    <Link href={`/email/runs/${j.last_run_id}`} className="inline-flex items-center gap-2 hover:underline">
                      {st && <span className={`inline-block size-2 rounded-full ${toneDot[st.tone]}`} />}
                      <span className="text-xs text-muted-foreground">
                        {relativeTime(j.last_started_at ? normalizeTs(j.last_started_at) : null, now)}
                      </span>
                    </Link>
                  ) : "—"}
                </td>
                <td className="mono px-4 py-2 text-right text-xs">{j.runs}</td>
                <td className={`mono px-4 py-2 text-right text-xs ${j.problems ? "text-warning" : ""}`}>
                  {rate == null ? "—" : `${rate}%`}
                </td>
                <td className="mono px-4 py-2 text-right text-xs">{formatMs(j.p50_ms)} / {formatMs(j.p95_ms)}</td>
                <td className="mono px-4 py-2 text-right text-xs">{formatUsd(j.avg_cost_usd)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
```

`web/components/obs/problems-list.tsx`:

```tsx
import Link from "next/link";
import type { Problem, RunStatus } from "@/lib/api";
import { RUN_STATUS } from "@/lib/view/run";
import { toneDot } from "@/lib/tone";
import { relativeTime } from "@/lib/format/datetime";
import { normalizeTs } from "@/lib/obs-utils";

export function ProblemsList({ problems }: { problems: Problem[] }) {
  if (problems.length === 0) {
    return <p className="px-4 py-8 text-center text-sm text-muted-foreground">Nothing failed in this window.</p>;
  }
  const now = Date.now();
  return (
    <ul className="divide-y divide-border/60">
      {problems.map((p) => {
        const href = p.trace_id
          ? `/observability/traces/${p.trace_id}`
          : p.run_id != null ? `/email/runs/${p.run_id}` : "/observability/logs";
        const dot = p.type === "run" ? toneDot[RUN_STATUS[p.status as RunStatus]?.tone ?? "danger"] : toneDot.danger;
        return (
          <li key={p.type === "run" ? `r${p.run_id}` : `l${p.id}`}>
            <Link href={href} className="flex items-start gap-3 px-4 py-2.5 hover:bg-accent/40">
              <span className={`mt-1.5 inline-block size-2 shrink-0 rounded-full ${dot}`} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 text-sm">
                  <span className="font-medium">{p.type === "run" ? p.kind : p.logger}</span>
                  <span className="text-xs text-faint">{relativeTime(normalizeTs(p.ts), now)}</span>
                </div>
                <div className="truncate text-xs text-muted-foreground">
                  {p.type === "run" ? p.error || p.summary || p.status : p.msg}
                </div>
              </div>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
```

- [ ] **Step 6: Overview page** — replace `web/app/observability/page.tsx`:

```tsx
import { getOverview } from "@/lib/api";
import { formatInt, formatMs, formatTokens, formatUsd } from "@/lib/format/number";
import { Panel } from "@/components/ui/panel";
import { EmptyState } from "@/components/ui/empty-state";
import { Kpi } from "@/components/obs/kpi";
import { WindowTabs } from "@/components/obs/window-tabs";
import { RunsChart } from "@/components/obs/runs-chart";
import { SpendChart } from "@/components/obs/spend-chart";
import { JobHealthTable } from "@/components/obs/job-health";
import { ProblemsList } from "@/components/obs/problems-list";

export const dynamic = "force-dynamic";

const WINDOWS: Record<string, { hours: number; label: string }> = {
  "24h": { hours: 24, label: "24h" },
  "7d": { hours: 24 * 7, label: "7d" },
  "30d": { hours: 24 * 30, label: "30d" },
};

export default async function ObservabilityOverview({
  searchParams,
}: {
  searchParams: Promise<{ window?: string }>;
}) {
  const { window = "24h" } = await searchParams;
  const win = WINDOWS[window] ?? WINDOWS["24h"];

  let data;
  try {
    data = await getOverview(win.hours);
  } catch (e) {
    return (
      <Panel>
        <EmptyState icon="TriangleAlert" title="Couldn't load observability data"
                    body={e instanceof Error ? e.message : "The backend API is unreachable."} />
      </Panel>
    );
  }
  const k = data.kpis;
  const finished = k.runs - k.running;
  const successPct = finished ? Math.round((k.runs_ok / finished) * 100) : null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Observability</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Runs, LLM spend and errors across rotom. Every row links to its trace.
          </p>
        </div>
        <WindowTabs param="window" value={window in WINDOWS ? window : "24h"} basePath="/observability"
                    options={Object.entries(WINDOWS).map(([value, w]) => ({ value, label: w.label }))} />
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Kpi label="Runs" icon="History" value={formatInt(k.runs)}
             sub={successPct == null ? "none finished" : `${successPct}% succeeded`} />
        <Kpi label="Problems" icon="TriangleAlert" value={formatInt(k.problems)}
             sub="failed · degraded · interrupted" tone={k.problems ? "warning" : undefined} />
        <Kpi label="LLM spend" icon="CircleDollarSign" value={formatUsd(k.cost_usd)}
             sub={`${formatTokens(k.input_tokens)} in · ${formatTokens(k.output_tokens)} out`} />
        <Kpi label="LLM calls" icon="Sparkle" value={formatInt(k.llm_calls)}
             sub={`p95 ${formatMs(k.llm_p95_ms)}${k.llm_errors ? ` · ${k.llm_errors} failed` : ""}`}
             tone={k.llm_errors ? "warning" : undefined} />
        <Kpi label="Error logs" icon="ScrollText" value={formatInt(k.error_logs)}
             sub="ERROR + CRITICAL" tone={k.error_logs ? "danger" : undefined} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Runs over time" sub={`Per ${data.bucket}, by outcome`}>
          <RunsChart series={data.runs_series} bucket={data.bucket} />
        </Panel>
        <Panel title="LLM spend" sub={`Per ${data.bucket}, by model`}>
          <SpendChart points={data.cost_series} buckets={data.buckets} bucket={data.bucket} />
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
        <Panel title="Job health" sub="Per run kind, this window" noPad>
          <JobHealthTable jobs={data.jobs} />
        </Panel>
        <Panel title="Recent problems" sub="Failed runs and error logs" noPad>
          <ProblemsList problems={data.problems} />
        </Panel>
      </div>
    </div>
  );
}
```

- [ ] **Step 7: Remove the old usage surface** — delete `web/components/tokens-chart.tsx` and `web/lib/view/usage.ts`; in `api/app/api/routes.py` delete the `/api/observability/usage` route; in `api/app/observability/sqlite_sink.py` delete `usage_by_model_day` and in `sink.py` its `QueryProvider` entry. Run `grep -rn "getUsage\|UsageAggregation\|usage_by_model_day\|tokens-chart\|view/usage" web api/app` → expect no hits.

- [ ] **Step 8: Verify**

Run: `cd api && uv run pytest -q` → PASS.
Run: `cd web && npm run lint && npm run build` → both succeed (type errors in `run-detail-live.tsx` for the changed `metrics` type must be fixed here: it only reads `model/input_tokens/output_tokens/avg_latency_ms`, which still exist).

- [ ] **Step 9: Commit**

```bash
git add web/lib/api.ts web/lib/nav.ts web/lib/format/number.ts web/app/observability/page.tsx \
  web/components/obs api/app/api/routes.py api/app/observability/sqlite_sink.py api/app/observability/sink.py
git rm web/components/tokens-chart.tsx web/lib/view/usage.ts
git commit -m "feat(web): observability overview dashboard (runs, spend, job health, problems)"
```

---

### Task 8: Web — Traces list, trace waterfall, run-detail integration

**Files:**
- Create: `web/lib/view/trace.ts`, `web/components/obs/traces-table.tsx`, `web/components/obs/trace-view.tsx`, `web/components/obs/messages.tsx`, `web/app/observability/traces/page.tsx`, `web/app/observability/traces/[traceId]/page.tsx`
- Modify: `web/app/email/runs/[id]/page.tsx`, `web/components/run-detail-live.tsx`

**Interfaces:**
- Consumes: `getTraces`, `getTrace`, types from Task 7, `formatMs/formatUsd`, `LogsPanel` (existing; `logs` prop accepts `LogEntry`-shaped rows).
- Produces: `buildWaterfall(spans)`, `spanCategory(span)`, `CATEGORY_STYLE`, `parseMessages(raw)`, `TRACE_TYPE_LABEL`; `<TraceView detail compact?>`; `<ChatMessages messages>`.

- [ ] **Step 1: Waterfall model** — create `web/lib/view/trace.ts`:

```ts
import type { SpanRow, TraceType } from "@/lib/api";
import { normalizeTs } from "@/lib/obs-utils";

export type SpanCategory = "run" | "agent" | "llm" | "tool" | "http" | "step";

export const CATEGORY_STYLE: Record<SpanCategory, { label: string; color: string }> = {
  run: { label: "Run", color: "var(--slate)" },
  agent: { label: "Agent", color: "var(--chart-2)" },
  llm: { label: "LLM", color: "var(--brand)" },
  tool: { label: "Tool", color: "var(--chart-3)" },
  http: { label: "API", color: "var(--chart-4)" },
  step: { label: "Step", color: "var(--muted-foreground)" },
};

export const TRACE_TYPE_LABEL: Record<TraceType, string> = { run: "Run", chat: "Chat", http: "API", other: "Other" };

/** Attributes rendered as content blocks, not in the attribute table. */
export const CONTENT_KEYS = new Set([
  "gen_ai.input.messages",
  "gen_ai.output.messages",
  "gen_ai.tool.call.arguments",
  "gen_ai.tool.call.result",
]);

export function spanCategory(s: SpanRow): SpanCategory {
  if (s.attributes["rotom.run.kind"] != null) return "run";
  if (s.operation === "invoke_agent") return "agent";
  if (s.operation === "chat") return "llm";
  if (s.operation === "execute_tool") return "tool";
  if (s.span_kind === "SERVER") return "http";
  return "step";
}

export interface WaterfallRow {
  span: SpanRow;
  depth: number;
  offsetPct: number;
  widthPct: number;
  category: SpanCategory;
}

const ms = (iso: string) => Date.parse(normalizeTs(iso));

/**
 * Depth-first span tree ordered by start time, with bar geometry relative to the trace.
 * Spans whose parent isn't present (root not exported yet) are rendered as roots.
 */
export function buildWaterfall(spans: SpanRow[]): { rows: WaterfallRow[]; totalMs: number } {
  if (spans.length === 0) return { rows: [], totalMs: 0 };
  const ids = new Set(spans.map((s) => s.span_id));
  const children = new Map<string, SpanRow[]>();
  const roots: SpanRow[] = [];
  for (const s of spans) {
    if (s.parent_span_id && ids.has(s.parent_span_id)) {
      const list = children.get(s.parent_span_id) ?? [];
      list.push(s);
      children.set(s.parent_span_id, list);
    } else {
      roots.push(s);
    }
  }
  const start = Math.min(...spans.map((s) => ms(s.start_time)));
  const end = Math.max(...spans.map((s) => ms(s.end_time)));
  const totalMs = Math.max(end - start, 1);
  const byStart = (a: SpanRow, b: SpanRow) => ms(a.start_time) - ms(b.start_time);
  const rows: WaterfallRow[] = [];
  const walk = (s: SpanRow, depth: number) => {
    rows.push({
      span: s,
      depth,
      category: spanCategory(s),
      offsetPct: ((ms(s.start_time) - start) / totalMs) * 100,
      widthPct: Math.max((s.duration_ms / totalMs) * 100, 0.4),
    });
    (children.get(s.span_id) ?? []).sort(byStart).forEach((c) => walk(c, depth + 1));
  };
  roots.sort(byStart).forEach((r) => walk(r, 0));
  return { rows, totalMs };
}

export interface ChatMessage {
  role: string;
  content: string;
  tool_calls?: { name: string; args: unknown }[];
}

/** Captured content attributes are JSON strings; returns null when absent or unparseable. */
export function parseMessages(raw: unknown): ChatMessage[] | null {
  if (typeof raw !== "string") return null;
  try {
    const v = JSON.parse(raw);
    return Array.isArray(v) ? (v as ChatMessage[]) : null;
  } catch {
    return null;
  }
}

/** Pretty-print a captured JSON payload; falls back to the raw string. */
export function prettyPayload(raw: unknown): string {
  if (typeof raw !== "string") return JSON.stringify(raw, null, 2);
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}
```

- [ ] **Step 2: Messages renderer** — create `web/components/obs/messages.tsx`:

```tsx
import type { ChatMessage } from "@/lib/view/trace";
import { cn } from "@/lib/utils";

const ROLE_STYLE: Record<string, string> = {
  system: "border-slate/40 bg-slate/8",
  user: "border-border bg-card-3",
  assistant: "border-brand-line bg-brand-soft",
  tool: "border-border bg-card",
};

export function ChatMessages({ messages }: { messages: ChatMessage[] }) {
  return (
    <div className="space-y-2">
      {messages.map((m, i) => (
        <div key={i} className={cn("rounded-md border px-3 py-2", ROLE_STYLE[m.role] ?? ROLE_STYLE.tool)}>
          <div className="mb-1 text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">{m.role}</div>
          {m.content && (
            <pre className="max-h-80 overflow-auto font-mono text-xs leading-relaxed break-words whitespace-pre-wrap">
              {m.content}
            </pre>
          )}
          {m.tool_calls?.map((c, j) => (
            <pre key={j} className="mt-1 overflow-x-auto rounded bg-card px-2 py-1 font-mono text-xs">
              → {c.name}({JSON.stringify(c.args)})
            </pre>
          ))}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Trace view (waterfall + inspector + logs)** — create `web/components/obs/trace-view.tsx`:

```tsx
"use client";

import { useMemo, useState } from "react";
import type { SpanRow, TraceDetail } from "@/lib/api";
import {
  buildWaterfall,
  CATEGORY_STYLE,
  CONTENT_KEYS,
  parseMessages,
  prettyPayload,
  spanCategory,
} from "@/lib/view/trace";
import { formatMs, formatTokens, formatUsd } from "@/lib/format/number";
import { Panel } from "@/components/ui/panel";
import { LogsPanel } from "@/components/logs-panel";
import { ChatMessages } from "@/components/obs/messages";
import { cn } from "@/lib/utils";

function Waterfall({
  spans,
  selected,
  onSelect,
}: {
  spans: SpanRow[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const { rows, totalMs } = useMemo(() => buildWaterfall(spans), [spans]);
  return (
    <div className="text-xs">
      <div className="flex border-b border-border px-3 py-1.5 text-[11px] text-faint">
        <div className="w-[38%] shrink-0">Span</div>
        <div className="flex flex-1 justify-between font-mono">
          <span>0</span>
          <span>{formatMs(totalMs / 2)}</span>
          <span>{formatMs(totalMs)}</span>
        </div>
      </div>
      {rows.map(({ span, depth, offsetPct, widthPct, category }) => {
        const isErr = span.status === "ERROR";
        const color = isErr ? "var(--destructive)" : CATEGORY_STYLE[category].color;
        return (
          <button
            key={span.span_id}
            type="button"
            onClick={() => onSelect(span.span_id)}
            className={cn(
              "flex w-full items-center px-3 py-1 text-left hover:bg-accent/50",
              selected === span.span_id && "bg-accent",
            )}
          >
            <div className="flex w-[38%] shrink-0 items-center gap-1.5 truncate" style={{ paddingLeft: depth * 14 }}>
              <span className="inline-block size-2 shrink-0 rounded-sm" style={{ background: color }} />
              <span className={cn("truncate font-mono", isErr && "text-destructive")}>{span.name}</span>
            </div>
            <div className="relative h-4 flex-1">
              <div
                className="absolute top-1 h-2 rounded-sm"
                style={{ left: `${offsetPct}%`, width: `${widthPct}%`, background: color, opacity: 0.85 }}
              />
              <span
                className="absolute top-0 font-mono text-[10px] text-muted-foreground"
                style={{ left: `min(calc(${offsetPct + widthPct}% + 4px), calc(100% - 48px))` }}
              >
                {formatMs(span.duration_ms)}
              </span>
            </div>
          </button>
        );
      })}
    </div>
  );
}

function Inspector({ span }: { span: SpanRow }) {
  const cat = spanCategory(span);
  const a = span.attributes;
  const input = parseMessages(a["gen_ai.input.messages"]);
  const output = parseMessages(a["gen_ai.output.messages"]);
  const plain = Object.entries(a).filter(([k]) => !CONTENT_KEYS.has(k));
  const exceptions = span.events.filter((e) => e.name === "exception");
  return (
    <div className="space-y-4 p-4 text-sm">
      <div>
        <div className="text-xs text-muted-foreground">{CATEGORY_STYLE[cat].label}</div>
        <div className="font-mono font-semibold break-all">{span.name}</div>
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span>{formatMs(span.duration_ms)}</span>
          <span className={span.status === "ERROR" ? "text-destructive" : ""}>{span.status}</span>
          {span.model && <span className="font-mono">{span.model}</span>}
          {span.cost_usd != null && <span>{formatUsd(span.cost_usd)}</span>}
        </div>
        {span.status_message && <p className="mt-2 text-xs text-destructive">{span.status_message}</p>}
      </div>

      {cat === "llm" && (
        <div className="grid grid-cols-4 gap-2 text-center text-xs">
          {([["In", span.input_tokens], ["Out", span.output_tokens], ["Cached", span.cache_read_tokens],
             ["Thinking", span.reasoning_tokens]] as const).map(([label, v]) => (
            <div key={label} className="rounded border border-border px-2 py-1.5">
              <div className="text-faint">{label}</div>
              <div className="font-mono tabular-nums">{v != null ? formatTokens(v) : "—"}</div>
            </div>
          ))}
        </div>
      )}

      {input && (
        <section>
          <h3 className="mb-2 text-xs font-semibold text-muted-foreground uppercase">Input</h3>
          <ChatMessages messages={input} />
        </section>
      )}
      {output && (
        <section>
          <h3 className="mb-2 text-xs font-semibold text-muted-foreground uppercase">Output</h3>
          <ChatMessages messages={output} />
        </section>
      )}
      {a["gen_ai.tool.call.arguments"] != null && (
        <section>
          <h3 className="mb-2 text-xs font-semibold text-muted-foreground uppercase">Arguments</h3>
          <pre className="overflow-x-auto rounded bg-card-3 p-2 font-mono text-xs">{prettyPayload(a["gen_ai.tool.call.arguments"])}</pre>
        </section>
      )}
      {a["gen_ai.tool.call.result"] != null && (
        <section>
          <h3 className="mb-2 text-xs font-semibold text-muted-foreground uppercase">Result</h3>
          <pre className="max-h-80 overflow-auto rounded bg-card-3 p-2 font-mono text-xs whitespace-pre-wrap">{prettyPayload(a["gen_ai.tool.call.result"])}</pre>
        </section>
      )}
      {exceptions.map((e, i) => (
        <section key={i}>
          <h3 className="mb-2 text-xs font-semibold text-destructive uppercase">Exception</h3>
          <pre className="max-h-80 overflow-auto rounded border-l-2 border-destructive/40 bg-destructive/8 p-2 font-mono text-xs whitespace-pre-wrap text-destructive">
            {String(e.attributes["exception.stacktrace"] ?? e.attributes["exception.message"] ?? "")}
          </pre>
        </section>
      ))}
      <section>
        <h3 className="mb-2 text-xs font-semibold text-muted-foreground uppercase">Attributes</h3>
        <table className="w-full text-xs">
          <tbody className="divide-y divide-border/60">
            {plain.map(([k, v]) => (
              <tr key={k}>
                <td className="py-1 pr-3 align-top font-mono text-muted-foreground">{k}</td>
                <td className="py-1 font-mono break-all">{typeof v === "string" ? v : JSON.stringify(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

/** Waterfall + span inspector + the trace's logs. `compact` hides logs (run detail has its own). */
export function TraceView({ detail, compact = false }: { detail: TraceDetail; compact?: boolean }) {
  const firstInteresting =
    detail.spans.find((s) => s.status === "ERROR") ?? detail.spans.find((s) => s.operation === "chat") ?? detail.spans[0];
  const [selectedId, setSelectedId] = useState<string | null>(firstInteresting?.span_id ?? null);
  const selected = detail.spans.find((s) => s.span_id === selectedId) ?? null;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[3fr_2fr]">
        <Panel title="Waterfall" sub={`${detail.spans.length} spans`} noPad>
          <Waterfall spans={detail.spans} selected={selectedId} onSelect={setSelectedId} />
        </Panel>
        <Panel title="Span" noPad className="xl:sticky xl:top-4 xl:max-h-[calc(100vh-2rem)] xl:overflow-auto">
          {selected ? <Inspector span={selected} /> : <p className="p-4 text-sm text-muted-foreground">Select a span.</p>}
        </Panel>
      </div>
      {!compact && (
        <LogsPanel logs={detail.logs} title="Logs in this trace" showLogger showRunId={false} className="max-h-[420px]" />
      )}
    </div>
  );
}
```

Check `LogsPanel`'s exact prop names in `web/components/logs-panel.tsx` (lines 116–135) and adapt the call if they differ.

- [ ] **Step 4: Traces table + list page** — create `web/components/obs/traces-table.tsx`:

```tsx
import Link from "next/link";
import type { RunStatus, TraceSummary } from "@/lib/api";
import { RUN_STATUS } from "@/lib/view/run";
import { TRACE_TYPE_LABEL } from "@/lib/view/trace";
import { toneDot } from "@/lib/tone";
import { relativeTime } from "@/lib/format/datetime";
import { formatMs, formatTokens, formatUsd } from "@/lib/format/number";
import { normalizeTs } from "@/lib/obs-utils";

function statusDot(t: TraceSummary): string {
  if (t.run_status) return toneDot[RUN_STATUS[t.run_status as RunStatus]?.tone ?? "muted"];
  if (t.status === "ERROR") return toneDot.danger;
  return t.error_count ? toneDot.warning : toneDot.success;
}

export function TracesTable({ traces }: { traces: TraceSummary[] }) {
  const now = Date.now();
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-border text-xs tracking-wider text-muted-foreground uppercase">
          <tr>
            <th className="px-4 py-2 font-medium">Trace</th>
            <th className="px-4 py-2 font-medium">Type</th>
            <th className="px-4 py-2 font-medium">Started</th>
            <th className="px-4 py-2 text-right font-medium">Duration</th>
            <th className="px-4 py-2 text-right font-medium">Spans</th>
            <th className="px-4 py-2 text-right font-medium">LLM</th>
            <th className="px-4 py-2 text-right font-medium">Tokens</th>
            <th className="px-4 py-2 text-right font-medium">Cost</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {traces.map((t) => (
            <tr key={t.trace_id} className="hover:bg-accent/40">
              <td className="px-4 py-2">
                <Link href={`/observability/traces/${t.trace_id}`} className="flex items-center gap-2 font-medium hover:underline">
                  <span className={`inline-block size-2 shrink-0 rounded-full ${statusDot(t)}`} />
                  <span className="truncate font-mono text-xs">{t.root_name}</span>
                  {t.error_count > 0 && <span className="text-xs text-destructive">{t.error_count} err</span>}
                </Link>
              </td>
              <td className="px-4 py-2 text-xs text-muted-foreground">{TRACE_TYPE_LABEL[t.trace_type]}</td>
              <td className="px-4 py-2 text-xs text-muted-foreground">{relativeTime(normalizeTs(t.start_time), now)}</td>
              <td className="mono px-4 py-2 text-right text-xs">{formatMs(t.duration_ms)}</td>
              <td className="mono px-4 py-2 text-right text-xs">{t.span_count}</td>
              <td className="mono px-4 py-2 text-right text-xs">{t.llm_calls || "—"}</td>
              <td className="mono px-4 py-2 text-right text-xs">
                {t.input_tokens + t.output_tokens ? formatTokens(t.input_tokens + t.output_tokens) : "—"}
              </td>
              <td className="mono px-4 py-2 text-right text-xs">{formatUsd(t.cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

Create `web/app/observability/traces/page.tsx`:

```tsx
import Link from "next/link";
import { getTraces } from "@/lib/api";
import { Panel } from "@/components/ui/panel";
import { EmptyState } from "@/components/ui/empty-state";
import { TracesTable } from "@/components/obs/traces-table";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

type Search = { type?: string; status?: string; q?: string; before?: string };

const TYPES = [
  { value: "", label: "All" },
  { value: "run", label: "Runs" },
  { value: "chat", label: "Chat" },
  { value: "http", label: "API" },
];
const STATUSES = [
  { value: "", label: "Any status" },
  { value: "error", label: "Errors" },
];

function href(base: Search, patch: Partial<Search>): string {
  const merged = { ...base, ...patch };
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(merged)) if (v) p.set(k, v);
  const qs = p.toString();
  return `/observability/traces${qs ? `?${qs}` : ""}`;
}

function Pills({ items, current, keyName, search }: {
  items: { value: string; label: string }[]; current: string; keyName: keyof Search; search: Search;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((i) => (
        <Link key={i.value} href={href(search, { [keyName]: i.value, before: undefined })}
              className={cn("rounded-full border px-3 py-1 text-xs",
                current === i.value ? "border-brand-line bg-brand-soft text-brand" : "border-border text-muted-foreground hover:text-foreground")}>
          {i.label}
        </Link>
      ))}
    </div>
  );
}

export default async function TracesPage({ searchParams }: { searchParams: Promise<Search> }) {
  const search = await searchParams;
  let page;
  try {
    page = await getTraces({ ...search, limit: 50 });
  } catch (e) {
    return (
      <Panel>
        <EmptyState icon="TriangleAlert" title="Couldn't load traces" body={e instanceof Error ? e.message : undefined} />
      </Panel>
    );
  }
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Traces</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          One trace per run, chat turn or API action — every step, LLM call and tool call inside it.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Pills items={TYPES} current={search.type ?? ""} keyName="type" search={search} />
        <Pills items={STATUSES} current={search.status ?? ""} keyName="status" search={search} />
        <form action="/observability/traces" className="ml-auto">
          {search.type && <input type="hidden" name="type" value={search.type} />}
          {search.status && <input type="hidden" name="status" value={search.status} />}
          <input name="q" defaultValue={search.q ?? ""} placeholder="Filter by name…"
                 className="h-8 w-56 rounded-md border border-border bg-card px-2.5 text-sm" />
        </form>
      </div>
      <Panel noPad>
        {page.traces.length === 0 ? (
          <EmptyState icon="Waypoints" title="No traces yet"
                      body="Traces appear when a run finishes, you chat with rotom, or an action is taken in the dashboard." />
        ) : (
          <TracesTable traces={page.traces} />
        )}
      </Panel>
      {page.next_before && (
        <div className="flex justify-center">
          <Link href={href(search, { before: page.next_before })} className="text-sm text-brand hover:underline">
            Older traces →
          </Link>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Trace detail page** — create `web/app/observability/traces/[traceId]/page.tsx`:

```tsx
import Link from "next/link";
import { notFound } from "next/navigation";
import { getTrace, type RunStatus } from "@/lib/api";
import { RUN_STATUS } from "@/lib/view/run";
import { spanCategory, TRACE_TYPE_LABEL } from "@/lib/view/trace";
import { formatMs, formatTokens, formatUsd } from "@/lib/format/number";
import { formatDateTime } from "@/lib/obs-utils";
import { Panel } from "@/components/ui/panel";
import { EmptyState } from "@/components/ui/empty-state";
import { Kpi } from "@/components/obs/kpi";
import { TraceView } from "@/components/obs/trace-view";

export const dynamic = "force-dynamic";

export default async function TraceDetailPage({ params }: { params: Promise<{ traceId: string }> }) {
  const { traceId } = await params;
  let detail;
  try {
    detail = await getTrace(traceId);
  } catch (e) {
    if (e instanceof Error && /\bAPI 404\b/.test(e.message)) notFound();
    return (
      <Panel>
        <EmptyState icon="TriangleAlert" title="Couldn't load this trace" body={e instanceof Error ? e.message : undefined} />
      </Panel>
    );
  }
  const ids = new Set(detail.spans.map((s) => s.span_id));
  const root = detail.spans.find((s) => !s.parent_span_id || !ids.has(s.parent_span_id)) ?? detail.spans[0];
  const llm = detail.spans.filter((s) => s.operation === "chat");
  const cost = llm.reduce((acc, s) => acc + (s.cost_usd ?? 0), 0);
  const tokens = llm.reduce((acc, s) => acc + (s.input_tokens ?? 0) + (s.output_tokens ?? 0), 0);
  const errors = detail.spans.filter((s) => s.status === "ERROR").length;
  const cat = spanCategory(root);
  const typeLabel = cat === "run" ? TRACE_TYPE_LABEL.run : cat === "agent" ? TRACE_TYPE_LABEL.chat : cat === "http" ? TRACE_TYPE_LABEL.http : TRACE_TYPE_LABEL.other;
  const runSt = detail.run ? RUN_STATUS[detail.run.status as RunStatus] : null;

  return (
    <div className="space-y-6">
      <div>
        <div className="text-xs text-muted-foreground">
          {typeLabel} trace · <span className="font-mono">{detail.trace_id}</span>
        </div>
        <h1 className="mt-1 font-mono text-xl font-semibold tracking-tight">{root.name}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {formatDateTime(root.start_time)}
          {detail.run && (
            <>
              {" · "}
              <Link href={`/email/runs/${detail.run.id}`} className="text-brand hover:underline">
                run #{detail.run.id}
              </Link>
              {runSt && <> · {runSt.label}</>}
              {detail.run.summary && <> · {detail.run.summary}</>}
            </>
          )}
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi label="Duration" icon="Timer" value={formatMs(root.duration_ms)} sub={`${detail.spans.length} spans`} />
        <Kpi label="LLM calls" icon="Sparkle" value={String(llm.length)} sub={`${formatTokens(tokens)} tokens`} />
        <Kpi label="Cost" icon="CircleDollarSign" value={formatUsd(llm.length ? cost : null)} />
        <Kpi label="Errors" icon="TriangleAlert" value={String(errors)} tone={errors ? "danger" : undefined}
             sub={errors ? "see red spans" : "none"} />
      </div>
      <TraceView detail={detail} />
    </div>
  );
}
```

- [ ] **Step 6: Run detail shows its trace** — `web/app/email/runs/[id]/page.tsx`: after `run` is loaded, fetch its trace (best-effort) and pass it down:

```tsx
  let trace = null;
  if (run.trace_id) {
    try {
      trace = await getTrace(run.trace_id);
    } catch {
      trace = null; // trace not exported yet (run still running) or pruned
    }
  }

  return <RunDetailLive initialRun={run} runId={id} trace={trace} />;
```

(import `getTrace` and `type TraceDetail` from `@/lib/api`.) In `web/components/run-detail-live.tsx`: add `trace` to the props (`trace: TraceDetail | null`), add a `Cost` column to the "Model usage" table (`formatUsd(m.cost_usd)` from `@/lib/format/number`), and render, just before `<LogsPanel …>`:

```tsx
      {trace && trace.spans.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">Trace</h2>
            <Link href={`/observability/traces/${trace.trace_id}`} className="text-xs text-brand hover:underline">
              Open full trace →
            </Link>
          </div>
          <TraceView detail={trace} compact />
        </div>
      )}
```

(import `TraceView` from `@/components/obs/trace-view`.)

- [ ] **Step 7: Verify**

Run: `cd web && npm run lint && npm run build` → both succeed.

- [ ] **Step 8: Commit**

```bash
git add web/lib/view/trace.ts web/components/obs web/app/observability/traces \
  "web/app/email/runs/[id]/page.tsx" web/components/run-detail-live.tsx
git commit -m "feat(web): traces list and trace waterfall with span inspector; run detail embeds its trace"
```

---

### Task 9: Web — LLM dashboard + trace links in logs

**Files:**
- Create: `web/app/observability/llm/page.tsx`
- Modify: `web/components/logs-panel.tsx`

**Interfaces:**
- Consumes: `getLlmStats`, `LlmStats`, `<Kpi>`, `<WindowTabs>`, `<SpendChart>`, `formatUsd/formatMs/formatTokens`.

- [ ] **Step 1: LLM page** — create `web/app/observability/llm/page.tsx`:

```tsx
import Link from "next/link";
import { getLlmStats, type LlmGroupStats } from "@/lib/api";
import { formatInt, formatMs, formatTokens, formatUsd } from "@/lib/format/number";
import { relativeTime } from "@/lib/format/datetime";
import { normalizeTs } from "@/lib/obs-utils";
import { Panel } from "@/components/ui/panel";
import { EmptyState } from "@/components/ui/empty-state";
import { Kpi } from "@/components/obs/kpi";
import { WindowTabs } from "@/components/obs/window-tabs";
import { SpendChart } from "@/components/obs/spend-chart";

export const dynamic = "force-dynamic";

const WINDOWS: Record<string, number> = { "1d": 1, "7d": 7, "30d": 30 };

function StatsTable({ rows, first }: { rows: (LlmGroupStats & { label: string; sub?: string | null })[]; first: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-border text-xs tracking-wider text-muted-foreground uppercase">
          <tr>
            <th className="px-4 py-2 font-medium">{first}</th>
            <th className="px-4 py-2 text-right font-medium">Calls</th>
            <th className="px-4 py-2 text-right font-medium">Errors</th>
            <th className="px-4 py-2 text-right font-medium">In</th>
            <th className="px-4 py-2 text-right font-medium">Out</th>
            <th className="px-4 py-2 text-right font-medium">Cached</th>
            <th className="px-4 py-2 text-right font-medium">p50 / p95</th>
            <th className="px-4 py-2 text-right font-medium">Cost</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {rows.map((r) => (
            <tr key={r.label} className="hover:bg-accent/40">
              <td className="px-4 py-2">
                <div className="font-mono text-xs">{r.label}</div>
                {r.sub && <div className="text-[11px] text-faint">{r.sub}</div>}
              </td>
              <td className="mono px-4 py-2 text-right text-xs">{formatInt(r.calls)}</td>
              <td className={`mono px-4 py-2 text-right text-xs ${r.errors ? "text-destructive" : ""}`}>{r.errors || "—"}</td>
              <td className="mono px-4 py-2 text-right text-xs">{formatTokens(r.input_tokens)}</td>
              <td className="mono px-4 py-2 text-right text-xs">{formatTokens(r.output_tokens)}</td>
              <td className="mono px-4 py-2 text-right text-xs">{r.cache_read_tokens ? formatTokens(r.cache_read_tokens) : "—"}</td>
              <td className="mono px-4 py-2 text-right text-xs">{formatMs(r.p50_ms)} / {formatMs(r.p95_ms)}</td>
              <td className="mono px-4 py-2 text-right text-xs">{formatUsd(r.cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function LlmPage({ searchParams }: { searchParams: Promise<{ window?: string }> }) {
  const { window = "7d" } = await searchParams;
  const days = WINDOWS[window] ?? 7;
  let data;
  try {
    data = await getLlmStats(days);
  } catch (e) {
    return (
      <Panel>
        <EmptyState icon="TriangleAlert" title="Couldn't load LLM stats" body={e instanceof Error ? e.message : undefined} />
      </Panel>
    );
  }
  const k = data.kpis;
  const now = Date.now();
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">LLM</h1>
          <p className="mt-1 text-sm text-muted-foreground">Every model call: spend, tokens, latency and failures.</p>
        </div>
        <WindowTabs param="window" value={window in WINDOWS ? window : "7d"} basePath="/observability/llm"
                    options={Object.keys(WINDOWS).map((w) => ({ value: w, label: w }))} />
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Kpi label="Spend" icon="CircleDollarSign" value={formatUsd(k.cost_usd ?? 0)} sub={`${formatInt(k.calls)} calls`} />
        <Kpi label="Tokens" icon="Hash" value={formatTokens(k.input_tokens + k.output_tokens)}
             sub={`${formatTokens(k.input_tokens)} in · ${formatTokens(k.output_tokens)} out`} />
        <Kpi label="Cache hit" icon="DatabaseZap" value={k.cache_hit_pct == null ? "—" : `${k.cache_hit_pct}%`}
             sub="of input tokens" />
        <Kpi label="Latency" icon="Timer" value={formatMs(k.p95_ms)} sub={`p95 · p50 ${formatMs(k.p50_ms)}`} />
        <Kpi label="Failures" icon="TriangleAlert" value={formatInt(k.errors)}
             sub={k.calls ? `${((k.errors / k.calls) * 100).toFixed(1)}% of calls` : "—"}
             tone={k.errors ? "danger" : undefined} />
      </div>

      <Panel title="Daily spend" sub="Stacked by model">
        <SpendChart points={data.daily} buckets={data.buckets} bucket="day" />
      </Panel>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="By model" noPad>
          <StatsTable first="Model" rows={data.by_model.map((m) => ({ ...m, label: m.model, sub: m.provider }))} />
        </Panel>
        <Panel title="By role" sub="classify · draft · chat" noPad>
          <StatsTable first="Role" rows={data.by_role.map((r) => ({ ...r, label: r.role }))} />
        </Panel>
      </div>

      <Panel title="Recent calls" sub="Newest first — open one to see its prompt and response" noPad>
        {data.recent.length === 0 ? (
          <EmptyState icon="Sparkle" title="No LLM calls in this window" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-border text-xs tracking-wider text-muted-foreground uppercase">
                <tr>
                  <th className="px-4 py-2 font-medium">When</th>
                  <th className="px-4 py-2 font-medium">Role</th>
                  <th className="px-4 py-2 font-medium">Model</th>
                  <th className="px-4 py-2 font-medium">Run</th>
                  <th className="px-4 py-2 text-right font-medium">Latency</th>
                  <th className="px-4 py-2 text-right font-medium">Tokens</th>
                  <th className="px-4 py-2 text-right font-medium">Cost</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {data.recent.map((c) => (
                  <tr key={c.span_id} className="hover:bg-accent/40">
                    <td className="px-4 py-2 text-xs">
                      {c.trace_id ? (
                        <Link href={`/observability/traces/${c.trace_id}`} className="text-brand hover:underline">
                          {relativeTime(normalizeTs(c.start_time), now)}
                        </Link>
                      ) : (
                        <span className="text-muted-foreground">{relativeTime(normalizeTs(c.start_time), now)}</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-xs">{c.role ?? "—"}</td>
                    <td className="px-4 py-2 font-mono text-xs">{c.model ?? "—"}</td>
                    <td className="px-4 py-2 text-xs text-muted-foreground">
                      {c.run_id ? <Link href={`/email/runs/${c.run_id}`} className="hover:underline">{c.run_kind} #{c.run_id}</Link> : "chat"}
                    </td>
                    <td className={`mono px-4 py-2 text-right text-xs ${c.status === "ERROR" ? "text-destructive" : ""}`}>
                      {c.status === "ERROR" ? "failed" : formatMs(c.duration_ms)}
                    </td>
                    <td className="mono px-4 py-2 text-right text-xs">{formatTokens(c.input_tokens + c.output_tokens)}</td>
                    <td className="mono px-4 py-2 text-right text-xs">{formatUsd(c.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
```

- [ ] **Step 2: Trace links in log rows** — in `web/components/logs-panel.tsx`:
- add `trace_id?: string | null;` and `span_id?: string | null;` to `LogRow`, and `"trace_id", "span_id"` to `knownKeys`;
- import `Link` from `next/link` and, inside the `showRunId && (…)` block after the run id span, render:

```tsx
            {log.trace_id && (
              <Link
                href={`/observability/traces/${log.trace_id}`}
                onClick={(e) => e.stopPropagation()}
                className="text-[11px] font-mono text-brand hover:underline"
              >
                trace
              </Link>
            )}
```

and widen the block's condition to `showRunId && (log.kind || log.run_id != null || log.trace_id)`.

- [ ] **Step 3: Verify**

Run: `cd web && npm run lint && npm run build` → both succeed.

- [ ] **Step 4: Commit**

```bash
git add web/app/observability/llm web/components/logs-panel.tsx
git commit -m "feat(web): LLM dashboard (spend, tokens, cache, latency, per model/role) and trace links in logs"
```

---

### Task 10: Docs, SQL cookbook, Makefile, end-to-end verification

**Files:**
- Create: `docs/observability/QUERIES.md`
- Modify: `docs/observability/README.md` (rewrite), `AGENTS.md`, `TODO.md`, `Makefile`

- [ ] **Step 1: Makefile targets** — add to `Makefile` (and to `.PHONY` and `help`):

```make
OBS_DB ?= api/data/observability.db

obs-sql:   ## open the observability DB in sqlite3 (try: SELECT * FROM v_runs ORDER BY run_id DESC LIMIT 10;)
	sqlite3 -box -header $(OBS_DB)

obs-ui:    ## browse/query the observability DB in Datasette (read-only) at http://127.0.0.1:8001
	uvx datasette $(OBS_DB) --port 8001 --setting sql_time_limit_ms 5000
```

Help lines: `@echo "make obs-sql  query observability.db with sqlite3"` and `@echo "make obs-ui   browse observability.db in Datasette"`.

- [ ] **Step 2: `docs/observability/QUERIES.md`** — a cookbook. Include at least these, each tested against a real DB with `make obs-sql`:

```markdown
# Querying rotom's telemetry

Everything is in `data/observability.db` (SQLite). `make obs-sql` opens it in sqlite3;
`make obs-ui` opens Datasette in the browser. DuckDB works too:
`duckdb -c "INSTALL sqlite; LOAD sqlite; ATTACH 'api/data/observability.db' AS obs (TYPE sqlite); SELECT * FROM obs.v_runs LIMIT 5"`.

Timestamps are UTC (`YYYY-MM-DD HH:MM:SS.ffffff`). Span attributes are JSON:
`json_extract(attributes, '$."gen_ai.tool.name"')`.

## Tables & views
| name | one row per |
|---|---|
| `run_log` / `v_runs` | unit of work (triage, reminder, draft…) — `v_runs` adds LLM calls, tokens, cost |
| `span` | OTel span (run, step, agent turn, tool call, LLM call, API request) |
| `v_traces` | trace (root span + rollups) |
| `v_llm_calls` | LLM call incl. role, tokens, cost, prompt/response |
| `v_tool_calls` | agent tool call incl. arguments/result |
| `v_errors` | ERROR span or ERROR/CRITICAL log line |
| `log_entry` | log line (joins to spans by `trace_id`/`span_id`, to runs by `run_id`) |

## Recipes

-- What failed today, with the trace to open
SELECT ts, source, what, substr(message, 1, 120) AS message, trace_id
FROM v_errors WHERE ts >= date('now') ORDER BY ts DESC;

-- Spend per day per model (last 14 days)
SELECT date(start_time) AS day, model, round(SUM(cost_usd), 4) AS usd, COUNT(*) AS calls
FROM v_llm_calls WHERE start_time >= date('now', '-14 days')
GROUP BY day, model ORDER BY day DESC, usd DESC;

-- Cost and duration per run kind (last 7 days)
SELECT kind, COUNT(*) AS runs, round(AVG(duration_ms)/1000, 1) AS avg_s,
       round(SUM(cost_usd), 4) AS usd, SUM(status != 'success') AS problems
FROM v_runs WHERE started_at >= date('now', '-7 days') GROUP BY kind ORDER BY usd DESC;

-- Where did the slowest triage spend its time?
WITH t AS (SELECT trace_id FROM v_runs WHERE kind = 'gmail_triage' ORDER BY duration_ms DESC LIMIT 1)
SELECT name, round(duration_ms) AS ms, operation, model
FROM span WHERE trace_id = (SELECT trace_id FROM t) ORDER BY start_time;

-- Slowest LLM calls this week, with the prompt start
SELECT start_time, role, model, round(duration_ms) AS ms, substr(input_messages, 1, 200) AS prompt
FROM v_llm_calls WHERE start_time >= date('now', '-7 days') ORDER BY duration_ms DESC LIMIT 10;

-- Which tools does the chat agent use, and how often do they fail?
SELECT tool, COUNT(*) AS calls, SUM(status = 'ERROR') AS errors, round(AVG(duration_ms)) AS avg_ms
FROM v_tool_calls GROUP BY tool ORDER BY calls DESC;

-- Everything (spans + logs) for one trace, in order
SELECT start_time AS ts, 'span' AS kind, name AS what, round(duration_ms) AS ms FROM span WHERE trace_id = :trace
UNION ALL
SELECT ts, 'log', level || ' ' || msg, NULL FROM log_entry WHERE trace_id = :trace
ORDER BY ts;

-- Cache effectiveness per model
SELECT model, SUM(cache_read_tokens) * 100.0 / NULLIF(SUM(input_tokens), 0) AS cache_hit_pct
FROM v_llm_calls GROUP BY model;
```

- [ ] **Step 3: Rewrite `docs/observability/README.md`** to describe v2: the data flow (log_schema → stdout + `log_entry`; spans → `SqliteSpanExporter` → `span`; views), what emits spans (table from the spec §3), the dashboards (Overview, Traces, LLM, Runs, Logs), `/metrics`, content capture + redaction, retention, the settings (`LOG_RETENTION_DAYS`, `TRACE_RETENTION_DAYS`, `OBS_CAPTURE_CONTENT`, `OBS_CONTENT_MAX_CHARS`, `METRICS_ENABLED`), key files, and gotchas: (a) GenAI semconv is "Development" — names live only in `semconv.py`; (b) only mutating API requests are traced; (c) a running run's trace appears in Traces only once its root span ends; (d) `asyncio.to_thread` propagates trace context, raw threads don't; (e) backfilled v1 LLM rows have `trace_id NULL` and `rotom.legacy=true`. Link the spec and `QUERIES.md`.

- [ ] **Step 4: `AGENTS.md`** — in the repo layout add `observability/` under `app/` ("tracing, log schema, metrics, dashboard queries — see docs/observability/"); under "Gotchas learned the hard way" add:

```markdown
- **Logging has one format file:** every log line (stdout + `log_entry` + dashboard) is built by
  `app/observability/log_schema.py` — change fields/redaction there, never in handlers. Noisy
  third-party loggers are capped in `logging_setup.NOISE_LEVELS` (httpx at INFO leaks the
  Telegram bot token via request URLs).
- **Tracing:** wrap new units of work in `record_run(kind)` (a root span + RunLog row) or
  `tracing.span(name)` (a step). LLM calls and agent tools are traced automatically. Spell
  OTel/GenAI attribute names only via `app/observability/semconv.py`. Tracing is inert until
  `init_tracing()` (tests use the `traced` fixture).
```

- [ ] **Step 5: `TODO.md`** — in "Observability — remaining" check off: tool-call counts (now spans + `v_tool_calls`); in "Code review follow-ups" check off: bound obs table growth (retention for spans + logs, blob no longer written), redact secrets from captured logs, `_prune_old_logs` timestamp comparison, run `_prune_old_logs` periodically, `UsageCallback` leak/on_llm_error, and mark "Propagate current_run_id into the triage worker thread" as **not a bug** (`asyncio.to_thread` copies contextvars; verified by `test_to_thread_keeps_span_parent`). Add a new "Observability v2 follow-ups" list: Telegram alerting on failures/cost spikes; optional OTLP exporter (`OTEL_EXPORTER_OTLP_ENDPOINT` → second span processor); Inngest run status sync; rotate the Telegram bot token (v1 logged it to stdout).

- [ ] **Step 6: End-to-end verification** (the `run` skill / `make dev`)
1. `cd api && uv run pytest -q` → all pass. `cd web && npm run lint && npm run build` → succeed.
2. Start the stack: `make dev` (API :8000, Inngest :8288, web :3000 or :3001).
3. Confirm stdout has **no** `api.telegram.org/bot<digits>:` URLs and no `uvicorn.access` lines; JSON lines inside runs carry `trace_id`.
4. Trigger work: the Runs page "Run now" button (POST → HTTP span + triage run) and a Telegram message (chat turn), if Telegram is enabled.
5. Browser (Playwright MCP or Chrome): visit `/observability`, `/observability/traces`, open a triage trace (waterfall shows `gmail_triage → triage.fetch → gmail.fetch … → triage.classify → chat …`; clicking a chat span shows prompt/response/tokens/cost), `/observability/llm`, `/observability/logs` (trace links), `/email/runs/<id>` (embedded trace). Screenshot each and look at them.
6. `make obs-sql` and run two recipes from `QUERIES.md`.
7. `METRICS_ENABLED=true` restart → `curl -s -H "Authorization: Bearer $API_TOKEN" localhost:8000/metrics | grep rotom_` shows series.

- [ ] **Step 7: Commit**

```bash
git add docs/observability/README.md docs/observability/QUERIES.md AGENTS.md TODO.md Makefile
git commit -m "docs(obs): v2 observability guide, SQL cookbook, make obs-sql/obs-ui"
```
