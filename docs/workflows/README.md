# Workflows (Inngest)

User-defined automation workflows — Python functions that run on a schedule or on demand,
with per-step retries and full run history in the Inngest dashboard. Supersedes the
YAML-engine sketch in PLAN.md §1.5 (and the design spec at
`docs/superpowers/specs/2026-06-07-workflows-inngest-design.md`).

## What it is

Each workflow is a Python file in `api/app/workflows/`. The Inngest OSS server handles
cron scheduling, event queuing, retry logic, and durable run state — deleting the need
for a homegrown executor, `workflow_runs`/`step_runs` tables, or a custom runs UI.

Workflow bodies call helpers from `app/workflows/lib.py` (`llm`, `run_script`, `notify`)
rather than raw SDKs — guardrails (LLM call budgets, script allow-lists, log scrubbing)
are retrofitted into these helpers later without touching workflow files.

External writes (GitHub issues, posts, email send) are **not in v1** — workflows are
read / process / Telegram-notify only until the Phase 5.2 policy layer lands.

## Topology

```
api container (existing FastAPI process, :8000)
  /api/*        existing routes
  /api/inngest  inngest.fast_api.serve(client, functions) — mounted in main.py

inngest container (official image, :8288)
  cron scheduler · event queue · retries · run-state store · dashboard UI
  calls back into /api/inngest over HTTP to execute each step
```

- Inngest down ⇒ workflows fail/queue visibly; triage and reminders (APScheduler) are
  unaffected.
- Manual triggers: `POST http://127.0.0.1:8288/e/dev` with
  `{"name":"workflows/<name>.requested","data":{}}`, or the `run_workflow` chat tool.

## Key files

| File | Role |
|---|---|
| `app/workflows/client.py` | Inngest client (`app_id="rotom"`, dev/prod mode from `INNGEST_DEV`) |
| `app/workflows/registry.py` | Collects all workflow functions for `serve()` |
| `app/workflows/lib.py` | Shared helpers: `llm(role, prompt)` · `run_script(name, *args)` · `notify(text)` |
| `app/workflows/hello.py` | Workflow 1: cron + event ping to Telegram (proves the loop) |
| `app/workflows/morning_digest.py` | Workflow 2: fetch → LLM summary → Telegram notify |
| `app/workflows/scripts/` | User-owned scripts called by `run_script` |
| `app/main.py` | Mounts `/api/inngest` via `inngest.fast_api.serve` |

## How to add a workflow

1. Create `api/app/workflows/<name>.py` — one file, one function.
2. Decorate with `@inngest_client.create_function(...)`:

```python
import inngest
from app.workflows.client import inngest_client
from app.workflows import lib

@inngest_client.create_function(
    fn_id="my-workflow",
    trigger=[
        inngest.TriggerEvent(event="workflows/my-workflow.requested"),
        inngest.TriggerCron(cron="0 9 * * *"),
    ],
    retries=2,
)
async def my_workflow(ctx: inngest.Context) -> str:
    async def fetch() -> str:
        return await lib.run_script("fetch_data.py")

    result = await ctx.step.run("fetch", fetch)

    async def summarise() -> str:
        return await lib.llm("chat", f"Summarise:\n{result}")

    summary = await ctx.step.run("summarise", summarise)

    async def send() -> str:
        await lib.notify(summary)
        return "sent"

    return await ctx.step.run("notify", send)
```

(SDK 0.5.18: the handler takes a single `ctx`; steps run via `await ctx.step.run(id, async_handler)` where the handler is an `async def`, not a lambda.)

3. Import the function in `app/workflows/registry.py` so `serve()` picks it up.
4. The `run_workflow` agent tool fires `workflows/<name>.requested` — no extra wiring
   needed once the function is registered.

Rules:
- Always include both `TriggerEvent("workflows/<name>.requested")` and `TriggerCron`
  (even a placeholder) so manual + scheduled triggers both work.
- Set `retries=2` on every function.
- Call `lib.llm / lib.run_script / lib.notify` — never raw SDKs from workflow files.
- `step.run(id, async_handler)` — each callable is a discrete retriable unit; keep IDs
  stable (Inngest uses them to resume after a failure).

## Local dev

```bash
# Terminal 1 — the full rotom API process (FastAPI + bot + scheduler + workflow mount):
cd api && uv run python -m app.main

# Terminal 2 — Inngest dev server (talks to the API):
npx inngest-cli@latest dev -u http://127.0.0.1:8000/api/inngest
```

Dashboard at `http://localhost:8288` — shows all registered functions, lets you trigger
manually, and displays per-step run history.

Manual event trigger (curl):
```bash
curl -X POST http://127.0.0.1:8288/e/dev \
  -H "Content-Type: application/json" \
  -d '{"name":"workflows/hello.requested","data":{}}'
```

Or via chat: `run_workflow hello` / `run_workflow morning-digest`.

## Compose

The `inngest` service in `docker-compose.yml` runs the official Inngest image.
Set `INNGEST_DEV` to the URL of the Inngest server (e.g. `http://inngest:8288`) in
the `api` service env so the client knows where to send events. The `client.py` bridge
reads `INNGEST_DEV` from `.env` via pydantic-settings and injects it into `os.environ`
before constructing the Inngest client.

## Gotchas we hit

- **pydantic-settings doesn't export `.env` into `os.environ`** — the Inngest SDK reads
  `INNGEST_DEV` directly from the environment, so `client.py` bridges the gap:
  reads from `settings.model_extra`, writes to `os.environ` if not already set (commit
  f765bac). Real env vars still win (docker/CI override).
- **SDK 0.5.18 handler signature** — the function receives a single `ctx` argument and
  steps via `await ctx.step.run(id, async_handler)`. Older examples show `(ctx, step)`
  as two args — that's a different SDK version.
- **`INNGEST_DEV` accepts a URL**, not just `"1"` — set it to the full Inngest server
  URL (e.g. `http://inngest:8288`) in compose; `"1"` or `"true"` works for local dev
  where the SDK defaults to `localhost:8288`.
- **Step IDs must be stable** — Inngest uses them to detect which steps have already
  completed when resuming after a retry. Changing an ID mid-run causes a fresh execution.
