# Observability

A self-contained telemetry layer: every autonomous unit of work (a "run") is recorded with
status, metrics, and logs; every LLM call's token usage + latency is captured; and all
structured logs are persisted and searchable. Surfaced in the dashboard as **Runs** (under
Email) and an **Observability** section (usage + charts + a logs explorer).

Lives in its own database (`data/observability.db`) so telemetry never contends with or
bloats the app's primary `rotom.db`.

## How it works

- **Separate DB** (`app/store/observability.py`): own `ObsBase` / engine / `get_obs_session()`,
  with `create_all()` + a migrations-lite `_migrate()` (`PRAGMA table_info` + `ALTER TABLE`)
  and `_prune_old_logs()` (retention). Models:
  - `RunLog` — `kind`, `started_at`/`finished_at`, `status` (`running` → `success`/`failure`),
    `summary`, `error`, `logs` (per-run captured JSONL).
  - `LLMUsage` — `provider`, `model`, `role`, `input_tokens`, `output_tokens`, `latency_ms`,
    `run_id` (nullable — null = "adhoc", e.g. a Telegram chat turn).
  - `LogEntry` — `ts` (indexed), `level`, `logger`, `msg`, `run_id` (indexed, loose int — no
    FK), `kind`, `extra` (JSON). The centralized log store.
- **Pluggable by design** (`app/observability/sink.py`): `ObservabilitySink` and
  `QueryProvider` Protocols, a `CompositeSink` that fans out and swallows per-sink failures,
  and a `get_sink()` / `get_query_provider()` factory selected by `OBSERVABILITY_BACKENDS`
  (default `sqlite`). Shipping telemetry to an external backend (BetterStack / Datadog / Loki)
  later means adding a sink — **no call-site changes**.
- **One instrumentation seam — `record_run(kind)`** (`sink.py`): a context manager that opens
  the run as `running`, propagates `current_run_id` (a `ContextVar`, so LLM usage + logs
  auto-attribute), captures the run's logs into a buffer, and finalizes status/summary/error/
  logs on exit. It marks `failure` if the body raises **or** calls `run.fail(...)` (degraded
  state), else `success`. Used by `gmail_triage` and `draft_generation`.
- **LLM capture** (`app/llm/provider.py`): `UsageCallback(BaseCallbackHandler)` times each
  call (`on_llm_start` → `on_llm_end`, keyed by LangChain's per-call UUID) and emits a
  `UsageEvent` (tokens + `latency_ms`) via `get_sink().record_usage()`, attributed to the
  current run or adhoc.
- **Structured JSON logging** (`app/logging_setup.py`): `setup_logging()` puts a `JsonFormatter`
  on stdout (every line `run_id`-stamped via `RunContextFilter`) **and** a `DbLogHandler` that
  persists every record into `LogEntry`. The handler is buffered (flush every 20 records or 5s)
  and reentrancy-safe (ignores `sqlalchemy.*` loggers, drops records mid-flush, never raises).
- **API** (`app/api/routes.py`): `GET /api/observability/runs`, `/runs/{id}` (per-model token
  + avg-latency metrics + captured logs), `/usage` (by model/day with latency), `/logs`
  (faceted: level/kind/run_id/text/time-range, id-cursor pagination); `POST /api/triage/trigger`
  schedules an immediate manual triage run.
- **Dashboard**:
  - **Runs** (`web/app/email/runs/`) — list + detail. Both live-refresh (poll every ~4s) while a
    run is `running`; detail shows status/duration/tokens/latency and a GitHub-Actions-style log
    panel.
  - **Observability** (`web/app/observability/`) — a usage table (tokens + avg latency, faceted by
    run/model) with a stacked **tokens-over-time chart** (shadcn/recharts), and a **Logs explorer**
    (`/observability/logs`) with a filter bar, level chips, time-range, a **live-tail** toggle, and
    cursor pagination.
  - Client polling goes through Next.js route-handler **proxies** (`web/app/api/*-proxy/`) so the
    bearer token stays server-side (`lib/api.ts` is `server-only`). Shared pure helpers in
    `web/lib/obs-utils.ts`; reusable `LogsPanel` component.

## Key files

- `api/app/store/observability.py` — DB, models, migrate, prune
- `api/app/observability/{events,sink,sqlite_sink}.py` — dataclasses, Protocols + `record_run`, SQLite impl
- `api/app/logging_setup.py` — JSON formatter, `RunContextFilter`, `DbLogHandler`, per-run buffer
- `api/app/llm/provider.py` — `UsageCallback`
- `api/app/api/routes.py` — `/api/observability/*`, `/api/triage/trigger`
- `web/app/email/runs/` · `web/app/observability/` · `web/app/api/*-proxy/`
- `web/components/{runs-list,run-detail-live,logs-explorer,logs-panel,tokens-chart}.tsx` · `web/lib/obs-utils.ts`

## Design decisions & gotchas

- **Status lifecycle.** A run is `running` until `finish_run`. If the process dies mid-run,
  `finish_run` never fires and the row is a **zombie** stuck in `running`. Auto-resolving these
  (an `interrupted` status + heartbeat + a 5-min reaper) and unifying *all* run sources
  (source/parent facets, Inngest) is specced separately — see
  [`superpowers/specs/2026-06-10-unify-run-sources-design.md`](../superpowers/specs/2026-06-10-unify-run-sources-design.md)
  — and is **not yet built**.
- **Interactive turns are not runs.** Telegram agent turns and draft chat record token usage as
  **adhoc** (`run_id = null`) and flow into the logs stream, but don't create `RunLog` rows
  (avoids flooding the Runs list). Draft *regeneration* (a discrete action) is a run.
- **Inngest workflows** keep their run history in the Inngest dashboard (:8288) for now; first-class
  tracking is part of the unify spec (v2).
- **DbLogHandler reentrancy.** SQLAlchemy logs are forced to WARNING and skipped by the handler;
  records emitted *during* a flush are dropped (not deferred) to prevent storms — acceptable log
  loss for a single-user app.
- **Naive datetimes.** SQLite returns tz-naive datetimes; the UI appends `Z` to parse as UTC.

## Operator setup

- `OBSERVABILITY_BACKENDS` — comma list of sinks (default `sqlite`).
- `LOG_RETENTION_DAYS` — `LogEntry` retention, pruned at startup (default `14`; `0` = keep all).
- `data/observability.db` is created automatically; it's gitignored (`*.db`).
