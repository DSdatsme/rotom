# Observability — Design

**Date:** 2026-06-09
**Status:** Designed, not yet built

## Goal

Two things, in priority order:

1. **(Phase 1) Runs board under Email** — a list of scheduled runs (Gmail triage cron to
   start), one selectable row each with a green/red status accent; opening a row shows that
   run's **metrics** (token usage) and **logs**.
2. **(Phase 2) Observability section** — a token-usage board: in/out token **counts by model
   over time**.

Plus a cross-cutting cleanup: **structured (JSON) logging** so run logs are captured cleanly
and we record more of the useful detail we currently drop.

This is a first cut. Workflow runs, cost ($), per-tool-call traces, and external export come
later; the schema and seams are built so they slot in additively.

## Delivery phases

- **Phase 1 — Runs under Email (build first).** Structured logging; `observability.db` with
  both tables; the `record_run` wrapper around the triage cron (logs + run-context); the LLM
  token callback (needed for per-run metrics); API `GET /runs` + `GET /runs/{id}`; UI "Runs"
  list + detail under the Email sidebar group.
- **Phase 2 — Observability board.** API `GET /usage` (aggregate by model/day); a top-level
  "Observability" sidebar section rendering the token-by-model-over-time board. Reuses the
  `LLMUsage` data already captured in Phase 1.

## Storage decision

A **separate `observability.db`** SQLite file — same engine, its own SQLAlchemy `Base`,
engine, and session factory, distinct from `rotom.db`. No new database technology. Telemetry
is append-heavy and **disposable** (purge/rotate freely) while operational data is precious,
so they don't share a file; and rotom already runs multiple SQLite files (`rotom.db`,
`scheduler.db`, `checkpoints.db`), so a fourth is idiomatic. Both observability tables live in
this one file, so the `llm_usage.run_id → run_log.id` FK is intra-database and valid.

- **Retention is unlimited locally** — SQLite keeps everything until an explicit purge
  (a future retention job; not in this spec).
- **Disaster recovery is out of scope here** — tracked in `TODO.md` (Infra/ops): a nightly
  *consistent* snapshot (`VACUUM INTO` / `.backup`, never a live `cp`) → versioned S3.
- New `config.py` property: `observability_db_path` → `f"{data_dir}/observability.db"`.
- New module `app/store/observability.py`: its own `ObsBase(DeclarativeBase)`, an engine
  bound to `observability_db_path`, `create_all` for these tables, and a `get_obs_session()`
  context manager mirroring `store/db.py`'s helper. SQLite is the **default backend, not a
  hard dependency** — see Pluggability below. Call `create_all` at startup in `main.py`
  alongside the existing DB init.

## Pluggability (the key constraint — swap/fan-out to other systems later)

Capture must NOT call SQLite directly. It goes through a backend-agnostic **sink interface**
so a future Langfuse / OpenTelemetry / Postgres backend is a drop-in with **zero call-site
changes**. This is the load-bearing abstraction of the whole design.

```python
# app/observability/events.py — transport-agnostic payloads (no SQLAlchemy types)
@dataclass(frozen=True)
class UsageEvent:
    provider: str; model: str; role: str
    input_tokens: int; output_tokens: int
    run_id: str | None; ts: datetime

@dataclass(frozen=True)
class RunResult:
    status: str; summary: str = ""; error: str = ""; logs: str = ""

# app/observability/sink.py
class ObservabilitySink(Protocol):
    def record_usage(self, e: UsageEvent) -> None: ...
    def start_run(self, kind: str) -> str: ...                 # returns an opaque run handle/id
    def finish_run(self, run_id: str, result: RunResult) -> None: ...

class QueryProvider(Protocol):                                 # read side for our dashboard
    def list_runs(self, limit: int) -> list[dict]: ...
    def get_run(self, run_id: str) -> dict | None: ...
    def usage_by_model_day(self, days: int) -> list[dict]: ...
```

- **`SqliteSink`** implements both `ObservabilitySink` and `QueryProvider` against
  `observability.db` (the v1 default).
- **`CompositeSink`** fans out one event to N sinks (each wrapped best-effort, so one slow/down
  backend never blocks or breaks another) — this is how you'd later send to SQLite **and**
  Langfuse simultaneously.
- A factory `get_sink()` / `get_query_provider()` reads config `OBSERVABILITY_BACKENDS`
  (default `"sqlite"`; e.g. `"sqlite,langfuse"` later) and returns the active sink/provider.
- Capture seams (`record_run`, the LLM callback) call `get_sink()`; the API calls
  `get_query_provider()`. Adding a backend = new class implementing the Protocol + a factory
  entry. No changes to seams, routes, or UI.
- The **structured JSON logs** are already a portable, parseable artifact — a future log sink
  (Loki/OTel) consumes the same records the run buffer captures, no reformatting.

> When the read backend is external (e.g. Langfuse owns the UI), `QueryProvider` may instead
> return links / proxied results, or the dashboard links out — the Protocol boundary keeps
> that decision isolated to one class.

## Structured logging (`app/logging_setup.py` — new)

Replace the plain `logging.basicConfig(...)` in `main.py` with a JSON setup using the stdlib
only (no new dependency):

- **`JsonFormatter(logging.Formatter)`** — emits one JSON object per line:
  `{"ts","level","logger","msg","run_id", ...extras}`. `ts` is ISO-8601 UTC. Any
  `logger.info(..., extra={...})` fields are merged in. Exceptions include `exc_info` text.
- **`RunContextFilter(logging.Filter)`** — reads the `current_run_id` ContextVar (see capture
  seams) and stamps `run_id` onto every record, so all logs emitted during a run are
  attributable without changing call sites.
- **`setup_logging()`** — configures the root/`rotom` logger with the JSON formatter on a
  `StreamHandler` (stdout — container/`journalctl` friendly) and the context filter. Called
  once at the top of `main.py`.

**Log more, deliberately.** As part of this, audit the hot paths and add structured,
leveled logs where we're currently silent or terse:
- Triage pipeline: per-account fetch start/counts/errors, classification batch size,
  rule-skips vs LLM-classified counts, drafts created, digest sent — at INFO, with counts in
  `extra`.
- LLM provider: model/role on each call at DEBUG; provider/quota errors at WARNING/ERROR.
- Scheduler: job start/finish already wrapped by `record_run`; log fire + outcome.
- Keep messages free of **email bodies / PII** (we log counts and IDs, not content) — same
  discipline as the triage prompt's untrusted-content rule.

## Data model (`app/store/observability.py`)

Both tables subclass `ObsBase` and are created by the observability engine's `create_all`.
`utcnow`/`StrEnum` follow `store/db.py` patterns.

```python
class RunStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"

class RunLog(ObsBase):
    __tablename__ = "run_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(64))                  # e.g. "gmail_triage"
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=RunStatus.SUCCESS)
    summary: Mapped[str] = mapped_column(Text, default="")         # basic output, if available
    error: Mapped[str] = mapped_column(Text, default="")
    logs: Mapped[str] = mapped_column(Text, default="")            # JSON log lines captured during the run
    usages: Mapped[list["LLMUsage"]] = relationship()             # token rows tagged with this run_id

class LLMUsage(ObsBase):
    __tablename__ = "llm_usage"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("run_log.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(32), default="")  # gemini | groq | anthropic
    model: Mapped[str] = mapped_column(String(64), default="")
    role: Mapped[str] = mapped_column(String(32), default="")      # classify | draft | chat
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
```

## Capture seams (record at one place each — callers don't change)

A module-level `contextvars.ContextVar[int | None]` named `current_run_id` ties the two seams
together: `record_run` sets it for the duration of a run; the LLM callback and the log filter
read it. None outside a run (e.g. ad-hoc Telegram chat) → those `LLMUsage` rows have
`run_id=NULL` and still feed the Phase-2 board.

### 1. Cron run log — wrapper around scheduled jobs (`app/scheduler/jobs.py`)

```python
def record_run(kind: str, fn):
    """Run fn() as a logged run: sets run-context, captures logs, records success/failure +
    summary. Re-raises on error (scheduler's own handling is unchanged — we only observe)."""
    sink = get_sink()
    run_id = sink.start_run(kind)                  # opaque handle (SqliteSink -> RunLog row id)
    token = current_run_id.set(run_id)
    handler = _attach_buffer()                     # in-memory logging.Handler on the "rotom" logger
    try:
        result = fn()                              # e.g. the triage pipeline
        sink.finish_run(run_id, RunResult(RunStatus.SUCCESS, summary=_summarize(result), logs=handler.text()))
        return result
    except Exception as e:
        sink.finish_run(run_id, RunResult(RunStatus.FAILURE, error=str(e), logs=handler.text()))
        raise
    finally:
        current_run_id.reset(token)
        _detach(handler)
```

- v1 wraps the **Gmail triage cron** (`kind="gmail_triage"`; summary like
  `"6 triaged · 1 draft · 2/5 accounts failed"`). Other crons wrap identically later.
- `_attach_buffer()` adds a handler (using the same `JsonFormatter`) that accumulates the
  run's log lines into a string; `.text()` returns the joined JSON lines stored in
  `RunLog.logs`. It captures only records emitted while the handler is attached.

### 2. LLM token usage — callback on the chat model (`app/llm/provider.py`)

Attach a LangChain `BaseCallbackHandler` when building models in `get_chat_model(role)`. On
`on_llm_end`, read the response's `usage_metadata` (`input_tokens`/`output_tokens`) and emit a
`UsageEvent` via `get_sink().record_usage(...)` tagged with `provider`/`model`/`role` (known
at build time) and `run_id=current_run_id.get()`. (The default `SqliteSink` turns that into an
`LLMUsage` row; another backend handles it its own way.)

- Fires for both `.invoke()` and `.with_structured_output(...).invoke()`.
- **Best-effort & non-blocking:** wrap the DB write in `try/except`, log on failure —
  telemetry must never break a classify/draft/chat call. Missing `usage_metadata` → record
  zeros and move on.

## API (`app/api/routes.py`, bearer auth, reads via `get_query_provider()`)

| route | phase | returns |
|---|---|---|
| `GET /api/observability/runs?limit=50` | 1 | recent `RunLog` rows newest-first: `[{id, kind, started_at, finished_at, status, summary}]` |
| `GET /api/observability/runs/{id}` | 1 | one run: the row + `error` + `logs` (parsed JSON lines) + **metrics** = its `LLMUsage` aggregated (in/out by model, totals) |
| `GET /api/observability/usage?days=14` | 2 | usage grouped by `model` and day: `[{day, model, input_tokens, output_tokens}]` + per-model totals |

`usage` groups via SQL `GROUP BY date(ts), model` (SQLite `date()`); day bucketing uses the
configured `TIMEZONE`.

## Web UI (`web/`)

Server components (`force-dynamic`), fetched via `lib/api.ts` (`getRuns`, `getRun`, and—Phase
2—`getUsage`); the token never reaches the browser.

**Phase 1 — Runs, under the existing "Email" sidebar group** (`components/app-sidebar.tsx`):
- **`app/email/runs/page.tsx`** — list of recent runs, one **row** each: `kind`, when
  (relative), duration, short `summary`; a **left accent bar / dot — green for success, red
  for failure** (dashboard's zinc/dark tokens + a status color). Rows link to detail.
- **`app/email/runs/[id]/page.tsx`** — run detail: header (kind, status, when, duration);
  **metrics** (token in/out by model + total for this run); a **logs** block (monospace,
  scrollable, rendered from the captured JSON lines); the `error` if it failed.

**Phase 2 — Observability, new top-level sidebar section** (`app/observability/page.tsx`):
- Token usage, counts only — table/bars grouped by model with in/out totals and a simple
  per-day over-time view (last N days). No cost column in v1.

## Error handling

- All telemetry writes (`LLMUsage`, `RunLog`, log buffering) are best-effort: failures are
  logged and swallowed; they never affect triage/draft/chat.
- `record_run` re-raises the job's exception after logging — the scheduler's existing error
  handling/alerting is unchanged.

## Testing (pytest; no live LLM/Gmail)

- `JsonFormatter` emits valid JSON with expected keys; `RunContextFilter` stamps `run_id`
  from the ContextVar (and `null` when unset).
- `record_run`: success path writes `SUCCESS` + summary + captured logs and sets/clears the
  ContextVar; failing `fn` writes `FAILURE` + error and re-raises; logs captured in both.
- LLM callback: a fake `on_llm_end` with `usage_metadata` → `get_sink().record_usage` called
  with correct model/role/tokens and the active `run_id`; missing usage → zeros, no crash.
- Sink: `SqliteSink` round-trips usage + runs; `CompositeSink` fans out to two fakes and
  isolates a failing one (the other still receives the event). Factory honors
  `OBSERVABILITY_BACKENDS`.
- API: `GET /runs` newest-first; `GET /runs/{id}` returns metrics + parsed logs; `GET /usage`
  groups by model/day; all require auth (use a fake `QueryProvider`).
- Web: `next build` typecheck.

## Out of scope (later versions)

- Workflow run rows (`kind="workflow:<name>"`) / Inngest integration.
- Cost ($) via a per-model price table.
- Per-tool-call / agent-step traces; latency percentiles.
- Telemetry **retention/purge** job and the **S3 DR snapshot** job (both in `TODO.md`).
- External provider export (Langfuse / OTel) — revisit only if local SQLite ever proves
  insufficient; rejected for now because the free-tier retention (≈30 days) is too short.

## Extensibility

The two tables are the seam everything hangs off: more `kind`s in `run_log`, more columns
(cost, latency) on `llm_usage`, more cards on the board — all additive, no schema rewrite.
Structured JSON logs mean run logs are already machine-parseable if we later ship them off-box.
This is the single observability surface the TODO calls for; it absorbs the older
"dashboard view of run history" item over time.

---

## As-built (2026-06-10)

Shipped, with these additions/changes beyond the original spec above. Component docs:
[`docs/observability/`](../../observability/).

**Built beyond spec:**
- **Centralized Logs explorer** — a third table `log_entry` (ts/level/logger/msg/run_id/kind/
  extra) + a buffered, reentrancy-safe `DbLogHandler` persisting every log; `GET /api/observability/logs`
  (faceted: level/kind/run_id/text/time-range, id-cursor pagination); a Datadog-style
  `/observability/logs` UI with level chips, time-range, **live-tail**, and expandable rows.
  `LOG_RETENTION_DAYS` (default 14) pruned at startup.
- **Latency** — `llm_usage.latency_ms` captured in the LLM callback (`on_llm_start`→`on_llm_end`);
  surfaced as avg latency per model in run detail and the usage table.
- **Live refresh** — Runs list + detail poll (~4s) while a run is `running`; client polling via
  Next.js route-handler proxies (`web/app/api/*-proxy/`) to keep the bearer token server-side.
- **Charts** — stacked tokens-over-time by model on the Observability board (shadcn/recharts).

**Changes vs spec:**
- **Run status lifecycle fixed** — runs open as `running` and flip to `success`/`failure` on
  finish (the spec/first cut defaulted to `success`, so in-flight/crashed runs looked green).
- **`record_run(kind)` seam** — the per-call-site boilerplate was DRYed into one context manager
  (sets status, ContextVar, log buffer, terminal status).
- **Draft chat is adhoc** — interactive chat turns are no longer run rows (avoids noise); only
  `draft_generation` (regenerate) and `gmail_triage` create runs.

**Still open (moved to the follow-on spec, [unify-run-sources](./2026-06-10-unify-run-sources-design.md)):**
- Zombie `running` rows on crash/restart → `interrupted` status + heartbeat + 5-min reaper.
- Unifying *all* run sources under one `RunLog`: `source`/`parent_run_id` facets + auto-nesting,
  and first-class **Inngest** run tracking (link-only today).
