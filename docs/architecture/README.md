# Core architecture

One Python process (`api/app/main.py`) runs four things on a single asyncio loop,
plus an Inngest sidecar for workflows:

```
┌──────────────────────── api container ────────────────────────┐
│  FastAPI (:8000, bearer auth)   ← Next.js dashboard (:3000)   │
│    └── /api/inngest             ← Inngest server (workflows)  │
│  python-telegram-bot (long poll) ← owner's Telegram chat      │
│    └── LangGraph agent (chat: open-ended tool-calling)        │
│  APScheduler (cron + date jobs: triage + reminders)           │
└────────────────────┬──────────────────────────────────────────┘
                     ▼                  ▲ invokes steps over HTTP
            data/ (SQLite files)   ┌────┴───────────────────────┐
            rotom.db    emails,    │ inngest container (:8288)  │
                        drafts,    │ cron/queue/retries/run     │
                        reminders, │ state + dashboard UI       │
                        dedup      └────────────────────────────┘
            checkpoints.db  LangGraph conversation state
            scheduler.db    APScheduler jobstore
            observability.db  runs, LLM usage/latency, centralized logs
```

**Two execution engines.** LangGraph (`app/agent/graph.py`, `create_react_agent` +
`AsyncSqliteSaver`) runs the *conversational* path — Telegram messages, where the
model decides which tools to chain. Inngest (`app/workflows/`, self-hosted) runs the
*deterministic* path — scheduled/triggered workflows as Python step functions with
retries and run history. They share only `get_chat_model`. See `docs/telegram-agent/`
and `docs/workflows/`.

## Key decisions

- **Single process, single volume** — portable: laptop today, VPS later. Postgres is a
  `DATABASE_URL` swap away (SQLAlchemy everywhere) but only when something demands it.
- **Swappable LLM providers** (`app/llm/provider.py`): `get_chat_model(role)` with roles
  `classify | draft | chat`, each independently configurable. Model strings support a
  `provider/model` prefix (e.g. `groq/llama-3.3-70b-versatile`) overriding the global
  `MODEL_PROVIDER`. Known providers: gemini, anthropic, groq.
- **Config** (`app/config.py`): pydantic-settings with `extra="allow"` — dynamically named
  vars like `GMAIL_<NAME>_REFRESH_TOKEN` land in `model_extra`. Real env vars beat .env.
- **Migrations-lite** (`app/store/db.py`): `create_all` for new tables + `_migrate()`
  doing `PRAGMA table_info` + `ALTER TABLE ADD COLUMN` for new columns.
- **HITL by construction**: the agent has no tool that sends to a third party. Email
  leaves the system only via the dashboard Send button (or, later, a Telegram approve
  button). `run_workflow` fires an *internal* Inngest event — and v1 workflows have no
  external-send step type, so that path stays inside the gate too.
- **Untrusted input is screened**: triaged email passes a prompt-injection guardrail
  (heuristics + borderline LLM judge) before classification; flagged mail is quarantined
  and never classified or auto-drafted. See `docs/guardrails/`.
- **Observability spans both engines**: a single `record_run(kind)` seam + a pluggable
  sink (own `observability.db`) records runs, LLM token/latency usage, and structured
  JSON logs — whether the work ran on the scheduler, an API call, or (later) Inngest.
  Telemetry is deliberately a separate DB so it never contends with `rotom.db`. See
  `docs/observability/`.

## Gotchas we hit

- SQLite returns **naive datetimes**; `as_utc()` in db.py re-attaches UTC before any
  comparison or `isoformat()` (otherwise JS parses them as local time).
- pydantic-settings does **not** inject .env into `os.environ` — read extras via
  `settings.model_extra`, with `os.environ` taking precedence (docker/CI).
- APScheduler jobstore pickles job functions — keep them **module-level** with
  scalar args only.
- Telegram hard-caps messages at 4096 chars — `channels/telegram.py` chunks on
  newline boundaries at 4000.
- Some providers return content as a **list of blocks**, not a string (Gemini, and
  Anthropic when thinking is on) — `extract_text()` in provider.py normalizes before
  `.strip()`.
- pydantic-settings not exporting to `os.environ` bit Inngest too: the SDK reads
  `INNGEST_DEV` from the real env, so `app/workflows/client.py` bridges the .env
  value into `os.environ` before constructing the client (real env still wins).

## Key files

`app/main.py` · `app/config.py` · `app/llm/provider.py` · `app/store/db.py` ·
`app/channels/telegram.py` · `app/agent/graph.py` (LangGraph) · `app/scheduler/jobs.py` ·
`app/workflows/` (Inngest) · `app/api/routes.py` · `app/observability/` + `app/store/observability.py` + `app/logging_setup.py`
