Create an Observability layer for a single-process Python (FastAPI + APScheduler +
LangGraph + Inngest) app with a Next.js dashboard.

It should have:

1. **A separate SQLite database** (`observability.db`) with its own engine/session, kept
   apart from the app's primary DB. Models:
   - `RunLog`: kind, started_at, finished_at, status (`running` → `success`/`failure`),
     summary, error, logs (captured JSONL text).
   - `LLMUsage`: provider, model, role, input_tokens, output_tokens, latency_ms, nullable
     run_id (null = "adhoc").
   - `LogEntry`: ts (indexed), level, logger, msg, run_id (indexed, loose int — no FK), kind,
     extra (JSON string).
   Use migrations-lite (`PRAGMA table_info` + `ALTER TABLE ADD COLUMN`) for new columns, and a
   startup prune of `LogEntry` older than a configurable retention (default 14 days).

2. **A pluggable sink/query layer**: `ObservabilitySink` and `QueryProvider` Protocols, a
   `CompositeSink` that fans out and swallows per-sink errors, a default SQLite implementation,
   and a factory selected by an `OBSERVABILITY_BACKENDS` env var. Adding an external backend
   (Datadog/BetterStack/Loki) must require no changes to call sites.

3. **One instrumentation seam**: a `record_run(kind)` context manager that opens a `running`
   row, propagates the run id via a `contextvars.ContextVar` (so LLM usage and logs
   auto-attribute), captures the run's logs into a buffer, and on exit writes the terminal
   status/summary/error/logs. It marks failure if the body raises or calls `run.fail()`.

4. **LLM token + latency capture**: a LangChain `BaseCallbackHandler` that times each call
   (`on_llm_start`→`on_llm_end`, keyed by the per-call UUID) and records provider/model/role/
   tokens/latency through the sink, attributed to the current run or adhoc.

5. **Structured JSON logging**: a formatter that emits one JSON object per log line stamped
   with the current run id, plus a buffered, reentrancy-safe DB handler that persists every
   record to `LogEntry` (ignore the ORM's own loggers; never raise; batch-flush).

6. **API endpoints**: list runs; run detail (per-model token + avg-latency metrics + logs);
   usage aggregated by model/day; a faceted logs query (level/kind/run_id/text/time-range with
   id-cursor pagination); and a manual "trigger run" endpoint.

7. **Dashboard UI**:
   - A Runs list + detail, both live-refreshing while a run is `running`, with a
     GitHub-Actions-style log panel.
   - An Observability section: a usage table + a stacked tokens-over-time chart (shadcn/recharts),
     and a Datadog-style Logs explorer with a filter bar, level chips, time-range, a live-tail
     toggle, and cursor pagination.
   - Client polling must go through server-side route-handler proxies so the API bearer token
     never reaches the browser.

Treat interactive chat turns as adhoc usage (not runs) to avoid flooding the Runs list.
