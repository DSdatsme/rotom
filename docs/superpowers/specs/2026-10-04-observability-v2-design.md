# Observability v2 — end-to-end traces, central logging, SQL-first, real dashboards

**Date:** 2026-10-04 · **Branch:** `feature/observability-v2` · **Builds on:**
`2026-06-09-observability-design.md`, `2026-06-10-unify-run-sources-design.md`

## Why

v1 records *that* a run happened, not *what happened inside it*. Measured on the live
`observability.db` (2026-10-04):

- 96% of `log_entry` is noise: 1,501 `httpx` rows (mostly Telegram long-poll) + 1,122
  `uvicorn.access` rows (the dashboard polling itself) vs ~40 app-level rows.
- **Secret leak:** httpx INFO lines contain `api.telegram.org/bot<TOKEN>/…`, persisted to
  stdout and `log_entry`. TODO's "redact captured logs" was never built.
- A run is one row + a text blob: no step timings (fetch/classify/draft), no tool calls, no
  link between a chat message, the agent, its tools and its LLM calls.
- Chat turns create no record beyond unattributed ("adhoc") token rows.
- Tokens only — no $ cost, no cached/thinking tokens, no prompts/responses.
- The log format is defined twice (stdout `JsonFormatter` vs. `DbLogHandler._persist`).

## Goals (owner's answers)

1. **Queryable end-to-end with plain SQL / standard tools** (sqlite3, DuckDB, Datasette).
   One `trace_id` follows trigger → run → steps → LLM/tool calls → logs.
2. **In-process, SQL-first:** everything stays in `./data/observability.db`; no new service.
3. **Opt-in Prometheus `/metrics`** endpoint behind an env var.
4. **LLM prompt/response captured**, truncated + secret-redacted.
5. **One central log schema**: changing the log format = editing one file; stdout, DB and
   per-run capture all go through it.
6. **Useful dashboards** in the existing Next.js app.

Non-goals (follow-ups): Telegram alerting, OTLP export to an external backend (a one-line
exporter addition later), Inngest status sync, evals.

## Decisions

- **OpenTelemetry SDK** (`opentelemetry-api`/`-sdk`) for trace/span ids + context
  propagation, with a **custom `SqliteSpanExporter`** (behind `BatchSpanProcessor`) writing
  to a `span` table. Names follow the OTel **GenAI semantic conventions** (still
  "Development" stability) — all GenAI attribute names live in one mapping module
  (`app/observability/semconv.py`) so upstream renames are a one-file change; the followed
  version is recorded in an `obs_meta` table.
- Hand-rolled instrumentation (no OpenInference/OpenLLMetry): rotom already owns the
  LangChain callback seam; this keeps GenAI-semconv names, zero extra deps, full control.
- **Timestamps:** every table keeps SQLAlchemy's UTC `YYYY-MM-DD HH:MM:SS.ffffff` format
  (consistent across tables so cross-table comparisons work; sqlite/DuckDB/Datasette parse
  it). The API keeps emitting ISO-with-offset via `_iso`.
- **Costs** via `genai-prices` (MIT, bundled offline price data). Priced on the *resolved*
  model (`response_metadata["model_name"]`, e.g. `gemini-3-flash-preview`) — aliases like
  `gemini-flash-latest` are unknown to it — falling back to the requested model; unknown →
  `cost_usd = NULL`, never an error. Gemini's `output_tokens` already includes thinking
  tokens; `input_tokens` includes cached tokens (passed as `cache_read_tokens`).
- **Metrics** via `prometheus_client` on a private registry, derived from finished spans (a
  `MetricsSpanProcessor`) + HTTP middleware. Disabled unless `METRICS_ENABLED=true`;
  `/metrics` requires the same bearer `API_TOKEN`.

## Components

### 1. Central logging — `app/observability/log_schema.py` (THE log format)

- `to_event(record) -> dict`: the single LogRecord→event mapping. Fixed keys, in order:
  `ts, level, logger, msg, trace_id, span_id, run_id, kind, file, line, exc` + any
  `extra=` fields. Values pass through `redact()`. Header comment: "change the log format
  here".
- `render(event) -> str` (JSON line). Used by the stdout formatter **and** the per-run
  buffer; `DbLogHandler` maps the same event dict onto `LogEntry` columns (extras → `extra`).
- `trace_id`/`span_id` come from `opentelemetry.trace.get_current_span()`.
- `app/logging_setup.py` becomes wiring only: handlers, **noise policy** (`httpx`,
  `httpcore`, `apscheduler.executors.default` → WARNING; `uvicorn.access` → WARNING, since
  HTTP spans + metrics replace it), `setup_logging()`.
- `app/observability/redact.py`: `redact(str) -> str` — masks the *values* of configured
  secrets (bot token, API token, LLM keys, GitHub/Claude tokens) plus regex shapes
  (Telegram `\d{6,}:[A-Za-z0-9_-]{30,}`, `Bearer …`, `AIza…`, `sk-ant-…`, `gsk_…`,
  `ghp_…`, `github_pat_…`) → `[REDACTED]`. Shared by logs and span content.
- `LogEntry` gains `trace_id`, `span_id` (indexed `trace_id`). One-time migration redacts
  the leaked token from existing `log_entry.msg/extra` and `run_log.logs/error`.

### 2. Tracing core — `app/observability/tracing.py`

- `init_tracing()` (idempotent; called in `main` after `init_obs_db`, `shutdown_tracing()`
  in the `finally`): `TracerProvider(resource={service.name: rotom})` +
  `RunAttributionProcessor` (on_start stamps `rotom.run_id` from `current_run_id`) +
  `BatchSpanProcessor(SqliteSpanExporter)` + `MetricsSpanProcessor` when enabled.
- `span(name, **attrs)` helper: `start_as_current_span`, records exceptions, sets ERROR.
- **`record_run` = root (or child) span.** Opens `start_as_current_span(kind)` with
  `rotom.run.kind/source/id`; `start_run` persists `run_log.trace_id`; status maps
  success/degraded→OK (degraded flagged via attribute), failure→ERROR. Call sites unchanged.
  Stops writing the `run_log.logs` blob — run logs are read from `log_entry` by `run_id`
  (old rows keep their blob as fallback).
- **Context:** `asyncio.to_thread` copies contextvars (OTel context included) — triage
  spans nest under the run. APScheduler async jobs start fresh roots. Raw threads
  (heartbeat, log-flush timer) need no context.

### 3. Spans emitted

| Where | Span | Key attributes |
|---|---|---|
| `record_run` | `{kind}` (root/child) | `rotom.run.kind/source/id`, `rotom.run.summary` |
| `agent.graph.run_agent` | `invoke_agent rotom` | `gen_ai.operation.name=invoke_agent`, `gen_ai.conversation.id`=thread, input/output content |
| tools (wrapped once in `toolkit`) | `execute_tool {name}` | `gen_ai.tool.name`, args/result content |
| every LLM call (callback) | `chat {model}` (CLIENT) | provider, request/response model, finish reasons, input/output/cache_read/reasoning tokens, `rotom.llm.role`, `rotom.cost_usd`, `gen_ai.input.messages`/`gen_ai.output.messages` |
| `run_triage` | `triage.fetch` (+ `gmail.fetch {account}`), `triage.dedup`, `triage.screen`, `triage.classify`, `triage.draft`, `triage.store` | counts per step |
| FastAPI middleware | `{METHOD} {route}` (SERVER) — **mutating methods only** (GET polling would drown traces); all requests feed metrics | `http.request.method`, `http.route`, `http.response.status_code` |

LLM spans come from `LlmTracingCallback` (replaces `UsageCallback`): start on
`on_chat_model_start`/`on_llm_start` with the current context as parent, kept in a dict by
LangChain run id, ended on `on_llm_end` **or `on_llm_error`** (fixes the v1 start-time
leak + dropped usage on error). Content: each message truncated to
`OBS_CONTENT_MAX_CHARS` (default 8000), redacted; `OBS_CAPTURE_CONTENT=true` by default.

### 4. Storage (`app/store/observability.py`)

```
span(span_id PK, trace_id, parent_span_id, name, span_kind, start_time, end_time,
     duration_ms, status, status_message, run_id,
     operation, provider, model, input_tokens, output_tokens, cache_read_tokens,
     reasoning_tokens, cost_usd,             -- promoted GenAI columns
     attributes JSON, events JSON)            -- idx: trace_id, start_time, run_id, operation
run_log  + trace_id (idx)        log_entry + trace_id (idx), span_id
llm_usage  retired: rows backfilled once into span (operation='chat', synthetic ids,
           cost computed); table left in place, no new writes.
obs_meta(key PK, value)          -- genai semconv version, backfill markers
```

**Views** (recreated on startup — the SQL query surface):
`v_runs` (run_log + LLM calls/tokens/cost/error spans), `v_traces` (one row per trace:
root name/type run|chat|http, start, duration, status, spans, LLM calls, tokens, cost,
errors, run_id), `v_llm_calls`, `v_tool_calls`, `v_errors` (ERROR spans ∪ ERROR+ logs).

**Retention:** `LOG_RETENTION_DAYS` (14) for `log_entry`, new `TRACE_RETENTION_DAYS` (30)
for `span`; `run_log` kept. Pruned at startup **and** by a daily scheduler job, using typed
SQLAlchemy deletes (fixes the v1 string-compare bug).

### 5. Metrics — `GET /metrics` (`METRICS_ENABLED`, bearer auth)

`rotom_runs_total{kind,source,status}`, `rotom_run_duration_seconds{kind}`,
`gen_ai_client_operation_duration_seconds{provider,model,role}`,
`gen_ai_client_token_usage_total{provider,model,role,token_type}`,
`rotom_llm_cost_usd_total{provider,model,role}`, `rotom_tool_calls_total{tool,status}`,
`http_server_request_duration_seconds{method,route,status_code}`,
`rotom_log_records_total{level}`.

### 6. Query API (sync `def` routes — SQLite reads off the event loop)

- `GET /api/observability/overview?hours=24|168|720` — KPIs, runs-by-status series,
  cost-by-model series, per-kind job health (last run/status, count, success %, p50/p95
  duration, avg cost), recent problems.
- `GET /api/observability/traces?limit&before&type&status&q` and `/traces/{trace_id}`
  (all spans + logs for the trace).
- `GET /api/observability/llm?days` — per model and per role: calls, error %, tokens by
  type, cost, p50/p95 latency; daily cost series; recent calls.
- `runs/{id}` gains `trace_id` and span-derived metrics; logs gains `trace_id` filter/field.
- `/usage` removed once the dashboard no longer calls it.
- Percentiles computed in Python (no SQLite percentile function; volumes are small).

### 7. Dashboards (web)

Nav "Observability": **Overview · Traces · LLM · Runs · Logs** (Runs moves here; URL kept).

- **Overview** `/observability` — window toggle (24h/7d/30d); KPI tiles (runs + success %,
  problems, LLM spend, LLM calls + p95, error logs); runs-over-time stacked by status;
  spend-by-model; job-health table; recent problems → trace.
- **Traces** `/observability/traces` — filterable table → **Trace detail**
  `/observability/traces/[traceId]`: header (status, duration, cost, tokens, run link),
  **waterfall** (indented span tree, offset/duration bars, errors red), span inspector
  (attributes; chat spans render prompt/response messages + token/cost breakdown; tool
  spans args/result; exceptions), logs in this trace.
- **LLM** `/observability/llm` — spend/tokens/cache-hit/p95 KPIs, daily spend by model,
  per-model + per-role tables, recent calls → trace.
- **Run detail** embeds the trace waterfall; **Logs** shows/links `trace_id`.

### 8. Raw SQL ergonomics

`make obs-sql` (sqlite3 `-box` on the DB), `make obs-ui` (`uvx datasette`, read-only), and
`docs/observability/QUERIES.md` — a cookbook of copy-paste queries against the views.

## Error handling

Observability never breaks the work it observes (v1 rule, kept): exporter, processors,
callback, middleware and redaction each catch + degrade (drop the span/metric, stdout
warning). Pricing lookups never raise. Query endpoints keep `_safe_obs_read`.

## Testing

pytest, no network, no real LLM: log schema keys + redaction + trace correlation; redact
patterns; exporter row mapping; record_run root/child spans + `run_log.trace_id`; LLM
callback spans from fake `LLMResult` (tokens, cost, error path, content truncation); tool
wrapper nesting; triage step spans with fakes; middleware (mutations traced, GETs not);
`/metrics` gated + authed; retention prune; backfill migration; query endpoints. Web:
`npm run lint` + `next build`; manual browser verification of each dashboard.
