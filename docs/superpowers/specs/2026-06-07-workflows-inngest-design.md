# Workflows on Inngest — design

Date: 2026-06-07 · Status: approved · Supersedes the YAML-engine sketch in PLAN.md §1.5

## Decision

User-defined workflows are **Python functions on Inngest** (self-hosted OSS server +
`inngest` Python SDK), not a homegrown YAML engine. Inngest provides cron/event
triggers, per-step retries, durable run state, and a dashboard with full run history —
deleting the executor, the `workflow_runs`/`step_runs` tables, and the runs UI from the
original plan. Temporal and similar were rejected as too heavy; Inngest is the same
category at personal-stack weight.

Decisions made during brainstorming:

| Question | Decision |
|---|---|
| First use cases | morning digest, email-adjacent automations, fetch+process+notify, script orchestration, scraping, log-parsing |
| Authoring | Python code (one file per workflow); YAML dropped — all durable-execution engines are code-first |
| External writes (GH issues, posts) | **not in v1** — read/process/Telegram-notify only |
| Control flow | plain Python (`if not x: return` replaces the planned skip_if_empty) |
| Scraping | user scripts in `workflows/scripts/`, called from steps |
| Triggers | cron (`TriggerCron`) + manual (event send from dashboard button / agent tool) |
| Guardrails | **deferred to TODO** — first goal is something running |
| Observability | Inngest dashboard (`:8288`) for now; rotom-dashboard integration later |

## Topology

```
api container (existing process)
  FastAPI :8000
    /api/*        existing routes
    /api/inngest  inngest.fast_api.serve(client, [functions])
  Telegram bot + APScheduler — UNCHANGED (triage & reminders stay on APScheduler)

inngest container (new, official image)
  cron scheduling, queue, retries, run state, dashboard UI :8288
  invokes /api/inngest over HTTP to execute steps
```

- Inngest down ⇒ workflow runs fail/queue visibly; triage and reminders unaffected.
- Local dev: Inngest dev server; app runs with `INNGEST_DEV=1` (no signing keys).
  Production signing keys are a deploy-time TODO.

## Code layout

```
api/app/workflows/
  client.py      # Inngest client (app_id="rotom", dev/prod mode from env)
  registry.py    # collects all workflow functions for serve()
  lib.py         # helpers: llm(role, prompt) · run_script(name, *args) · notify(text)
  hello.py       # workflow 1: cron ping to Telegram (proves the loop)
  morning_digest.py  # workflow 2: fetch (script/http) → llm summary → notify
  scripts/       # user-owned scrape/fetch scripts called by run_script
```

- One file per workflow; each exports an `@client.create_function(...)` with a cron
  trigger and/or `TriggerEvent("workflows/<name>.requested")` for manual runs.
- `retries=2` set per function. An `on_failure` handler pings Telegram
  "⚠ workflow <name> failed" (reuses the chunked sender).
- Workflow bodies call helpers from `lib.py`, not raw SDKs — guardrails (LLM call
  budgets, script allow-lists, log scrubbing) are retrofitted into these helpers later
  without touching workflow files.

## Manual trigger path

Dashboard "Run now" button and `run_workflow` agent tool both do
`client.send(Event(name="workflows/<name>.requested"))`. (Dashboard button may land
after v1 — the agent tool and Inngest dev UI cover manual runs initially.)

## Out of scope (explicit TODOs)

- Guardrails: `max_llm_calls` per run, script allow-list enforcement, secret-scrubbed
  step logs, external-write policy/HITL steps (`waitForEvent` makes this natural later)
- rotom-dashboard view of run history (Inngest API integration)
- Migrating gmail-triage / reminder crons onto Inngest
- Production signing keys + Inngest persistence/backup story

## Testing

- `lib.py` helpers unit-tested with fakes (no network/keys), same as the rest of api/.
- Workflow functions are thin composition — verified end-to-end via the Inngest dev
  server (trigger from its UI, watch steps), not unit-mocked in v1.
- CI unchanged: pytest must stay green; workflows import cleanly without a running
  Inngest server.

## Done when

`docker compose up` (or local dev equivalent) → `hello` fires on its cron and on a
manual event → Telegram receives the ping → `morning_digest` runs end-to-end →
both visible with per-step detail in the Inngest dashboard.
