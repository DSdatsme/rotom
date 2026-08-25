# Deep Research Workflow — Design Spec

**Date:** 2026-08-25
**Status:** Approved for implementation (v1)
**Owner:** Darshit

---

## 1. Context & goal

`idea-board` has a Claude Code skill, `verified-local-search` (`.agents/skills/verified-local-search/SKILL.md`), that finds hotels/restaurants matching a preference query and verifies the claims a plain search would just trust (fake-review filtering, menu-checking, price comparison). It's been tested manually inside a Claude Code session.

**Goal (v1):** make it usable from a phone without opening a terminal — submit a query from rotom's dashboard, walk away, get notified (Telegram and/or WhatsApp) when the research finishes. No new research logic gets built; this wires up delivery and background execution around the skill that already exists.

**Explicitly v1 only:**
- Restaurants/hotels queries via the existing skill, unchanged.
- Telegram and WhatsApp as delivery channels.
- Single query submission via a dashboard form (not chat-triggered, not scheduled/recurring).

### Non-goals (deferred)
- **Email delivery** — conflicts with rotom's existing "the agent never sends email, only the dashboard's human-gated Send button does" rule (`api/app/agent/toolkit.py`). Skipped for now rather than carving out an exception.
- **A new hand-rolled research engine.** This explicitly does *not* revisit `docs/research/2026-06-20-odysseus-analysis.md`'s "deep-research-as-a-feature" anti-recommendation — that entry is about Odysseus's own bespoke `Plan→Search→Extract→Synthesize` loop as application code. Here, all research reasoning (which candidates to check, how deep to verify, when to stop) stays entirely inside one opaque call to Claude Code running the existing skill. rotom-side code never models or re-implements that loop — it only wraps the one call as a durable job.
- Triggering research from the Telegram chat agent (dashboard-only entry point for v1).
- ntfy channel (out of scope; only Telegram + WhatsApp requested).
- Retrofitting existing notify call sites (triage digest, reminders) onto the channel abstraction below — only the new workflow uses it.

---

## 2. Constraint that shapes the architecture

rotom's API runs on a remote VPS with no GUI/Chrome. The skill's verification steps require Claude-in-Chrome, which only works paired with a real Chrome instance on a host where the extension is set up (confirmed working today: this Mac). So the actual Claude Code invocation **cannot** run inside rotom's process or its existing coding-agent Docker sandbox (`api/app/tools/github/sandbox.py`) — it has to happen on that Mac, reached from the VPS over Tailscale.

This is a deliberate, accepted limitation: the research step only works while that Mac is awake and reachable. Failure mode is handled explicitly (§6), not silently.

---

## 3. Architecture

```
┌─────────────────────┐        ┌──────────────────────────────────────┐
│ rotom dashboard      │  POST  │ rotom API (VPS)                       │
│ /research page       │───────▶│ /api/research → fires Inngest event   │
│ (search bar +        │        │                                        │
│  channel checkboxes) │        │  deep_research workflow (Inngest):    │
└─────────────────────┘        │   1. call research-runner (Tailscale) │
                                 │   2. record_run(kind="deep_research")│
                                 │   3. notify(result, channel=...)     │
                                 └───────────────┬────────────────────────┘
                                                  │ POST /run {query}
                                                  │ (Tailscale, shared secret)
                                                  ▼
                                 ┌──────────────────────────────────────┐
                                 │ deep-research-runner (new repo,       │
                                 │ this Mac — has Claude Code + paired   │
                                 │ Chrome)                               │
                                 │  spawns `claude -p "<query>"`         │
                                 │  headlessly, verified-local-search    │
                                 │  skill runs, returns markdown text    │
                                 └──────────────────────────────────────┘
```

Two repos change:
- **`rotom`** — new workflow, new API route, new dashboard page, extended notify channels.
- **`deep-research-runner`** (new, sibling folder under `~/personal/`) — small standalone Node service, this Mac only.

---

## 4. Component specs

### 4.1 `deep-research-runner` (new repo)

A single-purpose HTTP service, modeled on `claude-whatsapp-bridge`'s use of `@anthropic-ai/claude-agent-sdk` and rotom's own `sandbox.py` argv shape (minus the Docker wrapper — this runs directly on the host so it can reach the paired Chrome extension).

```
deep-research-runner/
  src/server.ts     # HTTP server, auth, request handling
  src/runClaude.ts  # spawns the query via claude-agent-sdk
  .env.example
  package.json
```

- `POST /run` — header `Authorization: Bearer <RUNNER_API_KEY>` (shared secret, same pattern as `whatsapp-gateway`'s `GATEWAY_API_KEY`). Body: `{"query": string}`.
- `runClaude(query)` calls `query({ prompt: query, options: { permissionMode: "bypassPermissions" } })` from `@anthropic-ai/claude-agent-sdk`, collects the final result text, returns it. `bypassPermissions` is a deliberate choice — this is an unattended background service on a machine you own, running a skill you've already reviewed; flagged here rather than picked silently.
- No `canUseTool` interception for `AskUserQuestion` (unlike `claude-whatsapp-bridge`, there's no human to route it to). Instead, the query sent to Claude prepends one line: *"This is an unattended background run — if anything is ambiguous, make the most reasonable assumption and state it plainly in your answer instead of asking."* This directly addresses the location-scope ambiguity we hit testing the skill manually (Uttan → Bhayandar/Gorai broadening).
- The skill must be reachable regardless of working directory: install it at `~/.claude/skills/verified-local-search` (copy or symlink from `idea-board`'s `.agents/skills/verified-local-search/`) rather than depending on `idea-board`'s repo path — decouples the runner from that repo.
- Timeout: research can take several minutes (multiple listings, browsing, verification). Use a generous bound — 10 minutes, matching `whatsapp-gateway` client's own default poll timeout for a similarly long-running human-in-the-loop wait. On timeout, kill the process and return an error the caller can report.
- Auth failure (bad/missing bearer token) → 401, no process spawned.

### 4.2 `api/app/workflows/deep_research.py` (new, rotom)

Follows `code_issue.py`'s shape, not `morning_digest.py`'s — this is on-demand/user-triggered, not scheduled, so it takes the same event-only trigger `code_issue` uses (no cron; the "always include both triggers" convention applies to the scheduled workflows, not this one):

```python
@inngest_client.create_function(
    fn_id="deep-research",
    trigger=[inngest.TriggerEvent(event="workflows/deep-research.requested")],
    retries=2,
)
async def deep_research(ctx: inngest.Context) -> str:
    query = ctx.event.data["query"]
    channels = ctx.event.data.get("channels", ["telegram"])

    async def run_research() -> str:
        return await call_runner(query)  # new helper, api/app/tools/research/runner_client.py
    result = await ctx.step.run("run-research", run_research)

    async def deliver() -> str:
        with record_run(kind="deep_research", source="inngest", summary=query) as run:
            run.logs = result
        for ch in channels:
            await notify(f"🔎 Deep research: {query}\n\n{result}", channel=ch)
        return "delivered"
    return await ctx.step.run("deliver", deliver)
```

The whole research call is **one Inngest step** — Inngest's retry wraps "the runner was unreachable," not any internal research logic (see §1 non-goals). The exact `record_run(...)` call signature (constructor args vs. attributes set on `run`, sync vs. async context manager) isn't pinned down above — verify against `api/app/observability/sink.py` during implementation rather than trusting this sketch verbatim.

### 4.3 New trigger route (rotom)

`work_on_issue` (`api/app/agent/toolkit.py:214-233`) is the reference for a *parameterized* trigger — `run_workflow` can't carry a payload. Since v1's entry point is the dashboard (not chat), this is a plain FastAPI route, not an agent tool:

```python
@router.post("/api/research")
async def start_research(req: ResearchRequest) -> dict:
    inngest_client.send_sync(inngest.Event(
        name="workflows/deep-research.requested",
        data={"query": req.query.strip(), "channels": req.channels},
    ))
    return {"status": "started"}
```

### 4.4 Notify channels — extend, don't retrofit

`docs/superpowers/specs/2026-06-14-notify-channels-design.md` designed a `NotificationChannel` Protocol + `notify(text, channel=...)` dispatcher, approved but **never implemented** (confirmed: `app/channels/notify.py` and `base.py` don't exist; only `telegram.py` does, and `lib.notify()` still calls `telegram.notify_owner` directly).

v1 here implements the minimal slice of that existing design, not the full doc:
- `app/channels/base.py` — the `NotificationChannel` Protocol, as originally specced.
- `app/channels/whatsapp.py` (new) — `WhatsAppChannel`, same shape as the doc's `NtfyChannel` but posting to the already-deployed `whatsapp-gateway`: `POST {WHATSAPP_GATEWAY_URL}/api/send` with `{"type": "notification", "text": text}`, `Authorization: Bearer {WHATSAPP_GATEWAY_API_KEY}`. `configured` → both env vars set. Raises `RuntimeError` on non-2xx/timeout, same as the ntfy spec's error contract.
- `app/channels/telegram.py` — add `TelegramChannel` alongside the existing bot code, exactly as originally specced.
- `app/channels/notify.py` (new) — the dispatcher, **channels = `("telegram", "whatsapp", "both")`** (no ntfy — not requested).
- **`app/workflows/lib.py`'s existing `notify(text)` is left untouched** — every current call site (triage digest, reminders) keeps calling it exactly as today. Only `deep_research.py` imports the new `app.channels.notify.notify` directly. This mirrors the original doc's own "existing call sites unchanged" rule, just scoped down to "existing call sites aren't touched at all in this pass."

### 4.5 Dashboard (rotom `web/`)

New `web/app/research/page.tsx`:
- A form: text input (query) + checkboxes for Telegram / WhatsApp (Telegram checked by default) → `POST /api/research`, then shows "Started — you'll be notified on the selected channel(s)."
- Below the form: past runs, reusing the existing generic runs list (`getRuns(50, { kind: "deep_research" })` from `web/lib/api.ts`, same pattern as `web/app/email/runs/page.tsx`). Exact component reuse (whether `RunsList` is generic enough to drop in directly, or needs a small prop) gets worked out in the implementation plan.
- New nav entry in `web/lib/nav.ts`'s `NAV_SECTIONS`.

---

## 5. Config changes

**rotom `.env.example`** — new block:
```
# ---- Deep research ----
RESEARCH_RUNNER_URL=          # e.g. http://<mac-tailscale-ip>:8787
RESEARCH_RUNNER_API_KEY=      # shared secret, matches the runner's RUNNER_API_KEY
WHATSAPP_GATEWAY_URL=         # your deployed whatsapp-gateway base URL
WHATSAPP_GATEWAY_API_KEY=     # matches whatsapp-gateway's GATEWAY_API_KEY
```
Matching typed fields added to `Settings` in `api/app/config.py`, following the existing lower_snake convention.

**`deep-research-runner/.env.example`** (new repo):
```
RUNNER_API_KEY=               # shared secret, matches rotom's RESEARCH_RUNNER_API_KEY
PORT=8787
```

---

## 6. Error handling

- **Runner unreachable / Mac asleep**: the `run-research` step throws, Inngest retries per `retries=2`, then on final failure the workflow needs to catch that and send `notify("⚠ Deep research failed: runner unreachable — is the Mac awake?", channel=...)` to the requested channels instead of going silent. **No existing rotom workflow does this today** (`code_issue.py` has no try/except or on-failure handler at all — an exhausted-retries failure there just surfaces in the Inngest dashboard, nothing user-facing) — this is new territory, not a reuse of an established pattern. Implementation needs to confirm the Inngest Python SDK's actual failure-handling mechanism (e.g. wrapping `ctx.step.run` in try/except within the function body, since Inngest step retries are usually transparent to the function's own control flow) rather than assuming one exists.
- **Runner timeout (>10 min)**: same failure path, message says "timed out" instead of "unreachable."
- **A requested channel unconfigured** (e.g. `WHATSAPP_GATEWAY_URL` unset): per the notify dispatcher's existing contract, log + skip that channel, don't fail the whole delivery if at least one other channel is configured.
- **Both requested channels fail to deliver**: `notify()` raises (per the original dispatcher spec); the workflow run is marked failed in `record_run` and visible in the dashboard's runs list even though no push notification arrived — the fallback surface.
- **Ambiguous location/attribute inside the research itself** (e.g. our Uttan test): not an error — handled by the runner's prepended instruction (§4.1) to state assumptions rather than block.

---

## 7. Testing

- `deep-research-runner`: mock the `claude-agent-sdk` `query()` call; test auth (missing/bad bearer → 401), timeout handling (kill + error response), and the happy path (valid query → 200 with result text).
- `api/app/channels/test_whatsapp_channel.py`: mirrors the ntfy design doc's test shape — correct URL/body/headers, `configured` logic, raises on non-2xx/timeout, no secret leaked in error messages.
- `api/app/channels/test_notify_dispatch.py`: extend/adapt the original doc's dispatch tests for the `("telegram", "whatsapp", "both")` set.
- `api/app/workflows/test_deep_research.py`: mock `call_runner` and `notify`; assert the three steps run in order, and that a runner failure triggers the failure-notify path instead of silently swallowing the error.
- Manual acceptance: submit a real query from `/research` on a phone, confirm the Mac's runner picks it up, confirm delivery on both Telegram and WhatsApp, confirm it shows up in the dashboard's research runs list.

---

## 8. File-by-file change list

**New (`deep-research-runner`, separate repo under `~/personal/`)**
- `src/server.ts`, `src/runClaude.ts`, `package.json`, `.env.example`, `README.md`.

**New (`rotom`)**
- `api/app/workflows/deep_research.py`
- `api/app/tools/research/runner_client.py` (the `call_runner()` HTTP helper)
- `api/app/channels/base.py`, `api/app/channels/whatsapp.py`, `api/app/channels/notify.py`
- `api/tests/test_whatsapp_channel.py`, `api/tests/test_notify_dispatch.py`, `api/tests/test_deep_research_workflow.py`
- `web/app/research/page.tsx`

**Modify (`rotom`)**
- `api/app/workflows/registry.py` — add `deep_research` to `WORKFLOW_FUNCTIONS`.
- `api/app/api/routes.py` — add `POST /api/research`.
- `api/app/channels/telegram.py` — add `TelegramChannel`.
- `api/app/config.py` — add the four new settings fields.
- `.env.example` — deep-research block.
- `web/lib/api.ts` — nothing new needed if `getRuns` already supports the `kind` filter (confirmed it does).
- `web/lib/nav.ts` — add a "Research" nav entry.

**Acceptance:** existing tests + new tests green; a real query submitted from the dashboard on a phone completes and arrives via the selected channel(s) while the Mac stays reachable; a run with the Mac asleep produces a clear failure notification instead of hanging silently.
