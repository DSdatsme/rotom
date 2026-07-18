# Workflows on Inngest — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** User-defined workflows as Python functions on a self-hosted Inngest server, mounted into rotom's existing FastAPI app, with a `hello` cron→Telegram workflow and a `morning_digest` (script → LLM → Telegram) workflow running end-to-end.

**Architecture:** One new package `api/app/workflows/` (client, registry, helper lib, one file per workflow) served at `/api/inngest` via `inngest.fast_api.serve()`. The Inngest server (dev server locally, container in compose) does cron scheduling, queueing, retries, run state, and the dashboard UI — rotom builds zero run-tracking. Existing APScheduler jobs (triage, reminders) are untouched.

**Tech Stack:** `inngest` Python SDK (Python ≥3.10; we're on 3.12), Inngest dev server / `inngest/inngest` Docker image, existing `get_chat_model`/`extract_text`/`send_chunked` helpers.

**Spec:** `docs/superpowers/specs/2026-06-07-workflows-inngest-design.md`

**Testing note:** Per user direction ("skip testing" ceremony, limited LLM tokens), only `lib.py` gets unit tests (fakes, no network/keys — spec requirement). Wiring tasks verify via imports/curl/dev-server UI. Live LLM verification needs user approval (one call).

---

### Task 1: Dependency + Inngest client

**Files:**
- Create: `api/app/workflows/__init__.py`, `api/app/workflows/client.py`
- Modify: `api/pyproject.toml` (via uv), `.env`, `api/.env`, `.env.example`

- [ ] **Step 1: Add the SDK**

```bash
cd /path/to/rotom/api && uv add inngest
```
Expected: resolves; `inngest` appears in pyproject + uv.lock.

- [ ] **Step 2: Create the client**

`api/app/workflows/__init__.py` — empty file.

`api/app/workflows/client.py`:
```python
"""Inngest client. Dev mode (no signing) unless INNGEST_DEV is unset in production."""

import os

import inngest

inngest_client = inngest.Inngest(
    app_id="rotom",
    is_production=os.getenv("INNGEST_DEV") is None,
)
```

- [ ] **Step 3: Env vars**

Append to `.env`, `api/.env`, and `.env.example`:
```
# ---- Workflows (Inngest) ----
INNGEST_DEV=1
```

- [ ] **Step 4: Verify import**

```bash
cd api && uv run python -c "from app.workflows.client import inngest_client; print(inngest_client.app_id)"
```
Expected: `rotom`

- [ ] **Step 5: Commit** — `git add -A api .env.example && git commit -m "workflows: add inngest SDK + client"`

---

### Task 2: Helper lib (llm / run_script / notify) + tests

**Files:**
- Create: `api/app/workflows/lib.py`, `api/app/workflows/scripts/.gitkeep`, `api/tests/test_workflow_lib.py`

- [ ] **Step 1: Write `lib.py`**

```python
"""Workflow step helpers. Workflows call these, never raw SDKs — future guardrails
(LLM budgets, allow-lists, log scrubbing) land here without touching workflow files."""

import asyncio
import sys
from pathlib import Path

from app.config import get_settings
from app.llm.provider import extract_text, get_chat_model

SCRIPTS_DIR = Path(__file__).parent / "scripts"


async def llm(role: str, prompt: str) -> str:
    """One LLM call (sync SDK moved off the event loop)."""
    model = get_chat_model(role, get_settings())
    msg = await asyncio.to_thread(model.invoke, prompt)
    return extract_text(msg.content)


async def run_script(name: str, *args: str, timeout: int = 120) -> str:
    """Run a script from workflows/scripts/ and return stdout. .py files run
    under the current interpreter; anything else must be executable."""
    path = (SCRIPTS_DIR / name).resolve()
    if SCRIPTS_DIR.resolve() not in path.parents:
        raise ValueError(f"Script {name!r} escapes the scripts directory")
    if not path.exists():
        raise FileNotFoundError(f"No script {name!r} in workflows/scripts/")
    cmd = [sys.executable, str(path), *args] if path.suffix == ".py" else [str(path), *args]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        raise RuntimeError(f"Script {name!r} timed out after {timeout}s")
    if proc.returncode != 0:
        raise RuntimeError(f"Script {name!r} failed ({proc.returncode}): {err.decode()[:500]}")
    return out.decode()


async def notify(text: str) -> None:
    """Send a (chunked) Telegram message to the owner."""
    from telegram import Bot

    from app.channels.telegram import send_chunked

    settings = get_settings()
    await send_chunked(Bot(settings.telegram_bot_token), settings.telegram_chat_id, text)
```

- [ ] **Step 2: Write tests** (`api/tests/test_workflow_lib.py`)

```python
"""Tests for workflow helpers — no network, no keys, no inngest server."""

import asyncio

import pytest

from app.workflows import lib


def test_run_script_runs_python(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "SCRIPTS_DIR", tmp_path)
    (tmp_path / "hello.py").write_text("print('hi from script')")
    out = asyncio.run(lib.run_script("hello.py"))
    assert out.strip() == "hi from script"


def test_run_script_rejects_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "SCRIPTS_DIR", tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        asyncio.run(lib.run_script("../evil.py"))


def test_run_script_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "SCRIPTS_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        asyncio.run(lib.run_script("nope.py"))


def test_run_script_failure_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "SCRIPTS_DIR", tmp_path)
    (tmp_path / "boom.py").write_text("import sys; sys.exit(3)")
    with pytest.raises(RuntimeError, match="failed"):
        asyncio.run(lib.run_script("boom.py"))


class FakeModel:
    def invoke(self, prompt):
        class Msg:
            content = [{"type": "text", "text": "summary!"}]  # Gemini-style block list
        return Msg()


def test_llm_extracts_text(monkeypatch):
    monkeypatch.setattr(lib, "get_chat_model", lambda role, settings: FakeModel())
    assert asyncio.run(lib.llm("chat", "x")) == "summary!"
```

- [ ] **Step 3: Run tests**

```bash
cd api && uv run pytest tests/test_workflow_lib.py -q
```
Expected: 5 passed. (If `extract_text` handles block lists differently, adjust FakeModel to match `app/llm/provider.py` — read it first.)

- [ ] **Step 4: Full suite** — `uv run pytest -q` → all pass.

- [ ] **Step 5: Commit** — `git commit -am "workflows: helper lib (llm/run_script/notify) + tests"`

---

### Task 3: hello workflow + registry + FastAPI mount

**Files:**
- Create: `api/app/workflows/hello.py`, `api/app/workflows/registry.py`
- Modify: `api/app/main.py`

- [ ] **Step 1: `hello.py`**

```python
"""Smoke-test workflow: proves cron + manual trigger + Telegram end-to-end."""

import datetime

import inngest

from app.workflows.client import inngest_client
from app.workflows.lib import notify


@inngest_client.create_function(
    fn_id="hello",
    trigger=[
        inngest.TriggerEvent(event="workflows/hello.requested"),
        inngest.TriggerCron(cron="0 9 * * *"),
    ],
    retries=2,
)
async def hello(ctx: inngest.Context) -> str:
    async def ping() -> str:
        now = datetime.datetime.now().strftime("%H:%M")
        await notify(f"👋 hello workflow ran at {now}")
        return "sent"

    return await ctx.step.run("ping-telegram", ping)
```

NOTE: check the installed SDK's signatures before assuming —
`uv run python -c "import inngest, inspect; print(inspect.signature(inngest.Inngest.create_function))"`.
If `trigger=` rejects a list on this version, use the cron trigger only and rely on the
dev-server UI's Invoke button for manual runs. If the function signature is
`(ctx, step)` (older SDKs) instead of `ctx.step`, adapt accordingly.

- [ ] **Step 2: `registry.py`**

```python
"""All workflow functions, handed to inngest.fast_api.serve()."""

from app.workflows.hello import hello

WORKFLOW_FUNCTIONS = [hello]
```

- [ ] **Step 3: Mount in `main.py`** — after `api = create_app(...)`:

```python
import inngest.fast_api

from app.workflows.client import inngest_client
from app.workflows.registry import WORKFLOW_FUNCTIONS

inngest.fast_api.serve(api, inngest_client, WORKFLOW_FUNCTIONS)
```

(Mount in main.py, NOT routes.py — tests build create_app() without inngest.)

- [ ] **Step 4: Verify route exists**

```bash
cd api && uv run python -c "
from app.api.routes import create_app
import inngest.fast_api
from app.workflows.client import inngest_client
from app.workflows.registry import WORKFLOW_FUNCTIONS
app = create_app(api_token='x')
inngest.fast_api.serve(app, inngest_client, WORKFLOW_FUNCTIONS)
print([r.path for r in app.routes if 'inngest' in r.path])"
```
Expected: `['/api/inngest']` (possibly listed per-method).

- [ ] **Step 5: Full suite + commit** — `uv run pytest -q` → pass; `git commit -am "workflows: hello workflow served at /api/inngest"`

---

### Task 4: Live smoke test with the Inngest dev server

**Files:** none (runtime verification). Zero LLM tokens.

- [ ] **Step 1: Start the dev server** (background):

```bash
npx inngest-cli@latest dev -u http://127.0.0.1:8000/api/inngest
```
Dashboard: http://127.0.0.1:8288

- [ ] **Step 2: Restart the rotom API** (it now has INNGEST_DEV=1 + the mount).

- [ ] **Step 3: Confirm app sync** — dev server "Apps" page shows `rotom` with function `hello`. If not synced, `curl -X PUT http://127.0.0.1:8000/api/inngest` to force registration.

- [ ] **Step 4: Manual trigger**

```bash
curl -s -X POST http://127.0.0.1:8288/e/dev -H 'Content-Type: application/json' \
  -d '{"name":"workflows/hello.requested","data":{}}'
```
(Or use the dashboard's Invoke button.)
Expected: run appears in dashboard with step `ping-telegram` green; "👋 hello workflow ran at HH:MM" lands in Telegram.

- [ ] **Step 5: Commit nothing — record results in the conversation.**

---

### Task 5: morning_digest workflow + example script

**Files:**
- Create: `api/app/workflows/scripts/top_hn.py`, `api/app/workflows/morning_digest.py`
- Modify: `api/app/workflows/registry.py`

- [ ] **Step 1: `scripts/top_hn.py`** (stdlib only):

```python
"""Print the top 10 Hacker News story titles, one per line."""

import json
import urllib.request


def get(url: str):
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.load(r)


ids = get("https://hacker-news.firebaseio.com/v0/topstories.json")[:10]
for i in ids:
    item = get(f"https://hacker-news.firebaseio.com/v0/item/{i}.json") or {}
    print(f"- {item.get('title', '?')} ({item.get('url', '')})")
```

- [ ] **Step 2: `morning_digest.py`**

```python
"""Morning digest: fetch top HN stories → LLM summary → Telegram. One LLM call/run."""

import inngest

from app.workflows.client import inngest_client
from app.workflows.lib import llm, notify, run_script


@inngest_client.create_function(
    fn_id="morning-digest",
    trigger=[
        inngest.TriggerEvent(event="workflows/morning-digest.requested"),
        inngest.TriggerCron(cron="30 8 * * *"),
    ],
    retries=2,
)
async def morning_digest(ctx: inngest.Context) -> str:
    stories = await ctx.step.run("fetch-hn", lambda: run_script("top_hn.py"))
    if not stories.strip():
        return "nothing fetched"

    async def summarize() -> str:
        return await llm(
            "chat",
            "Summarize these Hacker News stories in <=8 short bullet lines for a "
            f"busy engineer. Keep URLs for the 3 most interesting.\n\n{stories}",
        )

    summary = await ctx.step.run("summarize", summarize)

    async def send() -> str:
        await notify(f"🌅 Morning digest\n\n{summary}")
        return "sent"

    return await ctx.step.run("notify", send)
```

(`lambda: run_script(...)` returns a coroutine — if this SDK version wants the
callable to BE async, wrap as `async def fetch(): return await run_script("top_hn.py")`.)

- [ ] **Step 3: Register** — `registry.py`:

```python
from app.workflows.hello import hello
from app.workflows.morning_digest import morning_digest

WORKFLOW_FUNCTIONS = [hello, morning_digest]
```

- [ ] **Step 4: Verify script standalone (no LLM):**

```bash
cd api && uv run python app/workflows/scripts/top_hn.py | head -3
```
Expected: 3 story lines.

- [ ] **Step 5: Full suite + commit** — `uv run pytest -q`; `git commit -am "workflows: morning-digest (HN -> LLM summary -> telegram)"`

- [ ] **Step 6 (USER APPROVAL REQUIRED — costs 1 LLM call):** trigger `workflows/morning-digest.requested` via dev server; confirm digest in Telegram.

---

### Task 6: docker-compose service

**Files:**
- Modify: `docker-compose.yml`, `.env.example`

- [ ] **Step 1: Add service** to `docker-compose.yml`:

```yaml
  inngest:
    image: inngest/inngest:latest
    command: ["inngest", "start", "-u", "http://api:8000/api/inngest"]
    ports:
      - "8288:8288"
    environment:
      INNGEST_EVENT_KEY: ${INNGEST_EVENT_KEY:-local-event-key}
      INNGEST_SIGNING_KEY: ${INNGEST_SIGNING_KEY:-local-signing-key}
    volumes:
      - ./data/inngest:/var/lib/inngest
    depends_on:
      - api
```

And to the `api` service environment: `INNGEST_DEV: "1"` plus
`INNGEST_BASE_URL: http://inngest:8288` (check the SDK env-var name —
`uv run python -c "import inngest.const, inspect; print([e for e in dir(inngest.const) if 'ENV' in e or 'URL' in str(e)])"` or grep the SDK source for `base_url`).
`inngest start` (production mode) may require real signing keys; if so, document keys in `.env.example` — full compose e2e remains a TODO per spec.

- [ ] **Step 2: Validate** — `docker compose config -q` → exit 0.

- [ ] **Step 3: Commit** — `git commit -am "workflows: inngest service in compose"`

---

### Task 7: Agent tool, docs, plan bookkeeping

**Files:**
- Modify: `api/app/agent/toolkit.py`, `api/app/agent/prompts.py`, `PLAN.md`, `TODO.md`
- Create: `docs/workflows/README.md`

- [ ] **Step 1: `run_workflow` agent tool** (append to toolkit.py, add to ALL_TOOLS):

```python
@tool
def run_workflow(name: str) -> str:
    """Trigger a workflow by name (e.g. 'hello', 'morning-digest'). Runs asynchronously;
    results/notifications arrive via Telegram."""
    import asyncio

    import inngest as _inngest

    from app.workflows.client import inngest_client
    from app.workflows.registry import WORKFLOW_FUNCTIONS

    known = {f.id if hasattr(f, "id") else getattr(f, "fn_id", str(f)) for f in WORKFLOW_FUNCTIONS}
    # fn ids are kebab-case; accept either form
    slug = name.strip().lower().replace(" ", "-").replace("_", "-")
    asyncio.get_event_loop()  # we're inside the bot's loop; send() is async
    return _trigger(slug)
```

NOTE: the exact send call is
`await inngest_client.send(inngest.Event(name=f"workflows/{slug}.requested", data={}))` —
but LangChain `@tool` functions are sync here. Implement as a small sync wrapper using
`inngest_client.send_sync(...)` (the SDK provides send_sync). Final shape:

```python
@tool
def run_workflow(name: str) -> str:
    """Trigger a workflow by name (e.g. 'hello', 'morning-digest'). Results arrive on Telegram."""
    import inngest as _i

    from app.workflows.client import inngest_client

    slug = name.strip().lower().replace(" ", "-").replace("_", "-")
    inngest_client.send_sync(_i.Event(name=f"workflows/{slug}.requested", data={}))
    return f"Workflow {slug!r} triggered. Watch Telegram / the Inngest dashboard."
```

Add one line to the system prompt capabilities list:
`- run_workflow: trigger a named automation workflow`

- [ ] **Step 2: `docs/workflows/README.md`** — follow the docs/ convention (README per component): topology diagram, "add a workflow = one file in app/workflows/ + registry line", helper lib contract, dev-server howto, the SDK-signature gotchas found during Tasks 3–5.

- [ ] **Step 3: PLAN.md / TODO.md** — replace §1.5 body with a pointer:
"SUPERSEDED by Inngest — see docs/superpowers/specs/2026-06-07-workflows-inngest-design.md"
keeping the deferred-guardrails list; mirror in TODO.md (mark Iteration 2.5 items
done/superseded; add TODOs: guardrails-in-lib, dashboard run view, signing keys,
compose e2e, migrate triage/reminder crons — decide later).

- [ ] **Step 4: Full suite + push** — `uv run pytest -q`; `git push` (CI green).

---

## Self-review (done)

- **Spec coverage:** topology (T3/T6), code layout (T1–T5), manual trigger (T4 curl + T7 tool), retries+on_failure — on_failure is listed in spec as a nicety; folded into TODO bookkeeping in T7 if SDK signature proves awkward, otherwise add alongside T3 — acceptable per "guardrails later" direction; helpers+tests (T2), hello + morning_digest (T3/T5), compose (T6), docs/TODO (T7), CI-safe imports (T3 step 4, full-suite steps).
- **Placeholders:** none — every code step has code; SDK-signature uncertainty is handled with explicit verification commands and fallbacks, not hand-waving.
- **Type consistency:** `inngest_client` (T1) used throughout; `WORKFLOW_FUNCTIONS` (T3) consumed in T5/T7; helper names `llm/run_script/notify` consistent.
