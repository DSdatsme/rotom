# Unify Run Sources — Design

**Status:** v1 **implemented** (2026-06-13). Schema deltas, `RunStart`/`record_run` with
automatic parent/child nesting, per-source wiring (triage scheduler/manual, draft manual,
reminder_fire), heartbeat + stale-run reaper (`interrupted`), fail-safe instrumentation, and
the query/API/UI (source+kind facets, source badges, parent breadcrumb, sub-runs, Inngest
link) are all in. **Out of scope / deferred to v2:** first-class Inngest run tracking
(link-only today), chat-turn tracing.

## Goal

Make a single `RunLog` table the **source of truth** for every discrete, autonomous /
asynchronous unit of work rotom performs — regardless of which execution engine ran it
(APScheduler, direct API call, or self-hosted Inngest). One observability surface,
faceted by *what ran* and *how it started*, with automatic parent/child nesting.

## What counts as a "run"

> A **run** is a discrete, autonomous/async unit of work you'd want a green/red row +
> metrics + logs for: a cron triage pass, a workflow execution, a coding-agent task, a
> reminder firing.

> **Interactive request/response turns are NOT runs** — Telegram agent turns and draft
> chat stay adhoc (their LLM usage records with `run_id = null` and surfaces as "adhoc"
> in usage + the Logs explorer). This avoids flooding the Runs list. (Full chat→work
> tracing — making turns first-class runs — is explicitly **out of scope for v1**, see below.)

## The two facets

Every run carries:

- **`kind`** — *what ran*: `gmail_triage`, `draft_generation`, `workflow:<name>`,
  `coding_agent`, `reminder_fire`, …
- **`source`** — *how it was initiated*: `scheduler` (cron), `manual` (dashboard button),
  `chat` (Telegram command), `inngest` (internal event), `system` (default/other).

The Runs UI facets on both, so you can ask "all triage runs", "all workflow runs", or
"everything I kicked off from chat".

## Correlation: automatic nesting (v1)

We already propagate `current_run_id` via a `contextvars.ContextVar`. `record_run`
captures the **enclosing** run id as `parent_run_id` *before* setting the new one. So when
a run starts inside another run's context, the parent/child link forms automatically with
**zero caller changes**:

- An Inngest workflow (a run) that triggers triage logic (a run) → triage's parent = the workflow.
- The coding agent (a run, future F2) that spawns sub-tasks (runs) → sub-tasks' parent = the agent run.

Because chat/agent turns are **not** runs, a chat-triggered triage has no parent — it is
simply tagged `source = chat`. That is the intended behavior for v1.

## Schema deltas

All additive to `RunLog` in `api/app/store/observability.py` (`observability.db`), applied
via the existing migrations-lite `_migrate()` (`PRAGMA table_info` + `ALTER TABLE … ADD COLUMN`):

| Column | Type | Default | Notes |
|---|---|---|---|
| `source` | `str` (String(32)) | `"system"` | initiator facet |
| `external_id` | `str \| None` | `NULL` | e.g. Inngest run id |
| `external_url` | `str \| None` | `NULL` | deep link to the external engine's detail view |
| `parent_run_id` | `int \| None` | `NULL` | loose self-reference (no hard FK), indexed |
| `last_heartbeat_at` | `datetime \| None` | `NULL` | bumped while a run is open; powers the stale-run reaper (see Durability) |

Add an index on `parent_run_id` (children lookups). No data backfill needed — existing
rows get `source="system"`, null parents. `RunStatus` gains a terminal **`interrupted`**
value (see Durability).

## Transport-agnostic start payload

To keep the pluggable `ObservabilitySink` Protocol clean (matching the existing
`UsageEvent` / `RunResult` dataclasses in `events.py`), introduce a frozen dataclass:

```python
@dataclass(frozen=True)
class RunStart:
    kind: str
    source: str = "system"
    external_id: str | None = None
    external_url: str | None = None
    parent_run_id: str | None = None
```

`ObservabilitySink.start_run` changes from `start_run(self, kind: str) -> str` to
`start_run(self, run: RunStart) -> str`. Update `CompositeSink` and `SqliteSink` accordingly.

## `record_run` signature

```python
@contextmanager
def record_run(kind, *, source="system", external_id=None, external_url=None):
    parent = current_run_id.get()          # capture enclosing run BEFORE we overwrite it
    sink = get_sink()
    run_id = sink.start_run(RunStart(
        kind=kind, source=source,
        external_id=external_id, external_url=external_url,
        parent_run_id=parent,
    ))
    token = current_run_id.set(run_id)
    handler = _attach_buffer(run_id)
    ctx = RunContext(run_id)
    try:
        yield ctx
    except Exception as exc:
        sink.finish_run(run_id, RunResult(RunStatus.FAILURE, summary=ctx.summary or "Failed",
                                          error=ctx.error or str(exc), logs=handler.text()))
        raise
    else:
        status = RunStatus.FAILURE if ctx._failed else RunStatus.SUCCESS
        sink.finish_run(run_id, RunResult(status, summary=ctx.summary,
                                          error=ctx.error, logs=handler.text()))
    finally:
        current_run_id.reset(token)
        _detach(handler)
```

(Keeps `RunContext` / `.fail()` as-is.)

## Per-source wiring

- **gmail_triage** — `scheduled_gmail_triage_job(source="scheduler")`; the manual
  `/api/triage/trigger` endpoint schedules the job with `source="manual"` (pass via
  APScheduler `kwargs`). One function, two sources.
- **draft_generation** — regeneration route: `record_run("draft_generation", source="manual")`.
- **reminder_fire** — wrap `fire_reminder_job` in `record_run("reminder_fire", source="scheduler")`.
  No LLM; a cheap "fired & delivered at T" audit row.
- **Inngest workflows — deferred to v2 (link-only in v1).** v1 lands the `source` /
  `external_id` / `external_url` columns and the UI affordance to show a "View in Inngest →"
  link when present, but **creates no Inngest run rows**. This is intentional: Inngest is a
  durable engine that **replays the handler from the top on every step** (and resumes across
  restarts), so a naive `record_run` wrapper would emit one row per replay. Doing it right
  needs **Inngest middleware** (idempotent upsert keyed on the Inngest run id; terminal
  status from function-finished/failed hooks) — that is the v2 work. Until then, workflow
  run history stays in the Inngest dashboard (:8288), reachable via the link.

## Durability & restart handling

`record_run` only writes a terminal status on `with`-block exit. If the process dies
mid-run (crash, deploy, laptop sleep) `finish_run` never fires and the row is stuck
`running` forever. We resolve these "zombie" runs rather than backfilling:

- **New status `RunStatus.INTERRUPTED`** — a terminal state meaning "we lost track of this
  run" (distinct from a clean `failure`).
- **Heartbeat:** while a run is open, `record_run` bumps `last_heartbeat_at` on a
  lightweight background daemon thread (~60s interval), stopped + joined on `with` exit.
  Short runs (draft, most triage) finish before the first tick — fine, they exit with a
  normal terminal status and the reaper never looks at them.
- **Reaper (every 5 min):** an APScheduler job flips a run to `interrupted` when it is
  still `running` and looks dead:
  `status == running AND source != 'inngest' AND (last_heartbeat_at < now − 5min OR (last_heartbeat_at IS NULL AND started_at < now − 5min))`.
  A genuinely long run keeps heartbeating, so it is never reaped; a dead one stops
  heartbeating and is cleaned within ~5–10 min — no restart required. The reaper also runs
  once at startup, so zombies from a clean restart resolve immediately.

The reaper deliberately **excludes `source='inngest'`** (forward-compatibility): Inngest is
durable and resumes interrupted workflows, so its rows must never be force-failed because
our process bounced. In v1 Inngest creates no run rows (see wiring), so no inngest rows
exist yet to reap.

## Query / API / UI

- **QueryProvider / SqliteSink**: `list_runs` returns `source`, `external_url`,
  `parent_run_id`; accept optional `source`/`kind` filters. `get_run` additionally returns
  `children` (rows where `parent_run_id == id`) and the parent's id/kind for a breadcrumb.
- **API**: extend `GET /api/observability/runs` with optional `source` and `kind` query
  params. `GET /api/observability/runs/{id}` includes `source`, `external_url`, `parent`,
  and `children`.
- **UI** (`web/app/email/runs`):
  - Runs list: a `source`/`kind` facet filter bar; show a small `source` badge per row.
  - Run detail: a `source` badge; a **"View steps in Inngest →"** button when
    `external_url` is set; a parent breadcrumb (when nested) and a "Sub-runs" list linking
    to child runs.

## Testing (all mocked — NO live LLM calls)

- `record_run` persists `source` / `external_id` / `external_url` on the row.
- **Nesting**: a `record_run` opened inside another sets `parent_run_id` to the outer run; a
  top-level run has `parent_run_id = None`.
- `list_runs` filters by `source` and by `kind`.
- `get_run` returns the `children` list and parent reference.
- Manual-trigger path records `source="manual"`; the cron path records `source="scheduler"`.

## Resilience — fail-safe instrumentation (v1, done 2026-06-13)

Observability is **best-effort and must never break the work it observes**. If the
sink/DB is unavailable or failing, run tracking degrades to a stdout warning and the
wrapped body still runs.

- `get_sink()` **always** returns a `CompositeSink` — even for a single backend — so every
  sink call (`start_run`/`finish_run`/`record_usage`) is exception-isolated and logs a
  warning on failure instead of raising.
- `record_run` is fully defensive: `start_run` failure → `run_id = None` (logs/usage simply
  aren't attributed), the body **still executes**, and `finish_run`/log-buffer errors are
  swallowed with a warning. Exceptions from the *body* still propagate to the caller.
- Same posture extends to a future external sink: a flaky network backend can fail without
  taking down triage/draft/workflow execution.
- **Read path** (done): `/api/observability/*` routes wrap queries in `_safe_obs_read`,
  degrading to empty/null rather than 500 when the DB is unavailable — the dashboard stays
  usable and the failure is a stdout warning.

## Out of scope (v2+)

- **Inngest run tracking** — middleware-driven idempotent RunLog rows + status-sync for
  workflow executions (v1 is link-only, see wiring). The reaper already excludes
  `source='inngest'` in anticipation.
- **Chat-turn tracing** — making Telegram agent turns / draft chat first-class runs so
  chat-triggered work links back to the originating turn. Deferred (chosen "nesting only").
- **Cost / pricing** — explicitly not wanted.
- **Alerting rules** beyond the existing triage-failure Telegram ping.
- Shipping runs/logs to an external backend (BetterStack/Datadog/Loki) — the pluggable
  sink is the seam; build when local is outgrown.

## Sequencing

This is purely **additive** over the in-flight observability work (it only adds columns +
a few fields and wraps existing call sites). Implement after that lands and is verified
green, to avoid editing the same files concurrently.
