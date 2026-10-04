# Observability

Everything the system does is one queryable thing: a **trace** (OpenTelemetry spans) ties a
trigger to its run, steps, agent turns, tool calls, LLM calls and log lines. All of it lives in
`data/observability.db` (SQLite, separate from `rotom.db`) and is read with plain SQL or the
dashboard. No extra service.

- Design: [`superpowers/specs/2026-10-04-observability-v2-design.md`](../superpowers/specs/2026-10-04-observability-v2-design.md)
- SQL cookbook: [`QUERIES.md`](QUERIES.md) (`make obs-sql`, `make obs-ui`)

## Data flow

```
code ──span()/record_run()──▶ OTel SDK ──▶ BatchSpanProcessor ──▶ SqliteSpanExporter ──▶ span
                                 └──▶ MetricsSpanProcessor ──▶ /metrics (opt-in)
logging ──▶ log_schema.to_event() ──▶ stdout (JSON)
                                  ├──▶ log_entry (DbLogHandler, buffered)
                                  └──▶ per-run buffer
span + run_log + log_entry ──▶ views (v_runs, v_traces, v_llm_calls, v_tool_calls, v_errors)
                           ──▶ /api/observability/* ──▶ dashboard
```

- **Logs:** `app/observability/log_schema.py` is the only place the log line format is defined.
  Every line carries `trace_id`/`span_id` (from the current span) and `run_id`. Values go
  through `redact()`. Noisy third-party loggers are capped in `logging_setup.NOISE_LEVELS`
  (`httpx`/`httpcore`/`uvicorn.access`/`apscheduler.*`/`sqlalchemy` at WARNING).
- **Spans:** `init_tracing()` (called in `main` after `init_obs_db`) installs the provider,
  a `RunAttributionProcessor` (stamps `rotom.run_id`), and the exporter. Inert until called.
- **Views** are dropped and recreated on every startup, so definition changes ship with code.

## What emits spans

| Where | Span name | Notes |
|---|---|---|
| `record_run(kind)` | `{kind}` (root, or child if nested) | `rotom.run.kind/source/id/status`; also writes `run_log` with `trace_id` |
| `agent.graph.run_agent` | `invoke_agent rotom` | one per chat turn; `gen_ai.conversation.id` = thread |
| agent tools (wrapped once in the toolkit) | `execute_tool {name}` | arguments/result captured |
| every LLM call (`LlmTracingCallback`) | `chat {model}` (CLIENT) | provider, models, tokens (input/output/cache-read/reasoning), `rotom.llm.role`, `rotom.cost_usd`, prompt/response; ended on error too |
| `run_triage` | `triage.fetch` (+ `gmail.fetch {account}`), `triage.dedup`, `triage.screen`, `triage.classify`, `triage.draft`, `triage.store` | counts per step |
| FastAPI middleware | `{METHOD} {route}` (SERVER) | **POST/PUT/PATCH/DELETE only**; unmatched routes are labeled `<unmatched>` |

Cost comes from `genai-prices`, priced on the resolved model (`response_metadata.model_name`),
falling back to the requested one. Unknown model gives `cost_usd NULL`, never an error.

## Tables & views

See [`QUERIES.md`](QUERIES.md#tables--views). Tables: `run_log`, `span`, `log_entry`,
`obs_meta`; `llm_usage` is retired (backfilled into `span` once, no new writes). Views:
`v_runs`, `v_traces`, `v_llm_calls`, `v_tool_calls`, `v_errors`.

## Dashboards

Nav **Observability** (`web/app/observability/`; Runs keeps its URL under Email):

| Page | Path | Shows |
|---|---|---|
| Overview | `/observability` | 24h/7d/30d window; KPIs, runs by status, spend by model, per-kind job health, recent problems |
| Traces | `/observability/traces`, `/observability/traces/[traceId]` | filterable list; detail has the waterfall, span inspector (prompt/response, tokens, cost, args/result, exceptions) and the trace's logs |
| LLM | `/observability/llm` | spend, tokens, cache-hit, p95 latency; per model and per role; recent calls |
| Runs | `/email/runs`, `/email/runs/[id]` | list (supports `?kind=`) and detail with the embedded trace waterfall |
| Logs | `/observability/logs` | faceted explorer (incl. `trace_id`), live tail; lines link to their trace |

The browser never sees the bearer token: client polling goes through route-handler proxies
(`web/app/api/*-proxy/`), and `lib/api.ts` is `server-only`.

## `/metrics` (Prometheus)

Off by default. Set `METRICS_ENABLED=true` and restart; `GET /metrics` needs
`Authorization: Bearer $API_TOKEN` (404 when disabled). Private registry, fed by finished
spans and the HTTP middleware (all requests except `/metrics`, not just mutating ones):

```bash
curl -s -H "Authorization: Bearer $API_TOKEN" localhost:8000/metrics | grep rotom_
```

Series: `rotom_runs_total`, `rotom_run_duration_seconds`, `gen_ai_client_operation_duration_seconds`,
`gen_ai_client_token_usage_total`, `rotom_llm_cost_usd_total`, `rotom_tool_calls_total`,
`http_server_request_duration_seconds`, `rotom_log_records_total`.

## Content capture & redaction

LLM prompts/responses and tool arguments/results are stored as span attributes, each
truncated to `OBS_CONTENT_MAX_CHARS` and passed through `redact()` (`observability/redact.py`):
values of configured secrets (bot/API tokens, LLM keys, GitHub/Claude tokens) plus regex
shapes (Telegram bot token, `Bearer ...`, `AIza...`, `sk-ant-...`, `gsk_...`, `ghp_...`,
`github_pat_...`) become `[REDACTED]`. Set `OBS_CAPTURE_CONTENT=false` to store no content.
A one-time startup migration scrubs secrets already in `log_entry` / `run_log`.

## Retention

`log_entry` is pruned by `LOG_RETENTION_DAYS`, `span` by `TRACE_RETENTION_DAYS` (by
`end_time`); `run_log` is kept. Pruning runs at startup and daily at 04:00 (scheduler job
`obs-prune`). `0` = keep everything.

## Settings

| Env var | Default | Meaning |
|---|---|---|
| `LOG_RETENTION_DAYS` | `14` | `log_entry` retention |
| `TRACE_RETENTION_DAYS` | `30` | `span` retention |
| `OBS_CAPTURE_CONTENT` | `true` | store prompts/responses/tool payloads |
| `OBS_CONTENT_MAX_CHARS` | `8000` | per-message/payload truncation |
| `METRICS_ENABLED` | `false` | expose `/metrics` |
| `OBSERVABILITY_BACKENDS` | `sqlite` | run/usage sink list (v1 seam) |

## Key files

- `api/app/observability/` — `semconv.py` (attribute names), `tracing.py` (init, `span()`),
  `sink.py` (`record_run`), `span_exporter.py`, `llm_tracing.py`, `log_schema.py`, `redact.py`,
  `pricing.py`, `metrics.py`, `http.py` (middleware), `queries.py` (dashboard queries)
- `api/app/store/observability.py` — models, migrations, views, retention
- `api/app/logging_setup.py` — handler wiring and noise policy only
- `api/app/api/routes.py` — `/api/observability/*`, `/metrics`
- `web/app/observability/`, `web/app/email/runs/`, `web/app/api/*-proxy/`

## Gotchas

- **GenAI semconv is "Development" stability.** Attribute names are spelled only in
  `semconv.py`; an upstream rename is a one-file change.
- **Only mutating API requests are traced** (GET polling would drown traces). Metrics still
  see every request.
- **A running run's trace appears in Traces only once its root span ends.** Until then it is
  visible only on the Runs page.
- **`asyncio.to_thread` propagates trace context; raw threads don't.** Spans started in a bare
  `threading.Thread` become new roots.
- **Backfilled v1 LLM rows** have `trace_id NULL` and `rotom.legacy=true`; they appear in
  `v_llm_calls`/`v_runs` but not in `v_traces`.
- **Zombie runs.** A run stays `running` until it finishes; stale ones are marked
  `interrupted` by the `run-reaper` scheduler job (every 5 min).
- **Interactive turns are not runs.** Chat turns are `invoke_agent` traces with no `run_log` row.
- **Naive datetimes.** Stored UTC without offset; the API emits ISO-8601 with `+00:00`.
