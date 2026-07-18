# rotom — Code & Design Review (2026-06-21)

Full-codebase review (~4.8k LOC Python API + ~7.1k LOC Next.js web). 19 parallel subsystem
reviewers produced **87 findings**; the **1 Critical + 17 High were re-verified line-by-line
against source — all real**. Medium/Low are reviewer-flagged leads (the automated verify pass
was cut short by a rate limit), so spot-check Lows before acting.

> Browsable version (all 87, grouped by theme): https://claude.ai/code/artifact/c9d45ff0-bdd4-4aef-ba0a-fa5fd13200e2

**Counts:** 1 critical · 17 high · 30 medium · 39 low/nit.

**Context note:** the default `model_provider` is `gemini` (not Anthropic) — the blocking-I/O
findings hold for any provider since all SDK calls are synchronous. Intentional single-user
non-goals (no RBAC, SQLite single-file, no login UI) were excluded by design.

---

## Remediation plan (Critical + High)

Status legend: `[x]` done · `[ ]` pending. **All Critical+High items below are done** (branch `fix/code-review-crit-high`, +19 tests). Batches are ordered by danger and grouped by file.

### Batch 1 — Sandbox & auth security
- [x] **C1 (CRIT):** session dir outside the worktree + never stage it — `code_issue.py`, `sandbox.py`, `runner.py`
- [x] **C2 (HIGH):** drop OAuth token from container env path / `--network none` for reviewers — `sandbox.py`
- [x] **E1 (HIGH):** fail-fast on empty/placeholder `API_TOKEN` + constant-time bearer compare — `config.py`, `routes.py`

### Batch 2 — Prompt-injection defense
- [x] **D2 (HIGH):** judge failure → quarantine borderline (fail-safe), not drop — `service.py`
- [x] **D1 (HIGH):** route all non-malicious new emails to the judge, not just heuristic-borderline — `service.py`

### Batch 3 — Event-loop blocking & SQLite concurrency
- [x] **A1 (HIGH):** offload blocking LLM/Gmail I/O via `asyncio.to_thread` in routes + async chat-triage tool — `routes.py`, `toolkit.py`
- [x] **B1 (HIGH):** WAL + `busy_timeout` on both engines — `db.py`, `observability.py`
- [x] **B2 (HIGH):** generate draft bodies outside the open write transaction — `pipeline.py`
- [x] **B3 (HIGH):** serialize triage + idempotent insert (catch `IntegrityError`) — `pipeline.py`, `routes.py`

### Batch 4 — Data integrity
- [x] **F1 (HIGH):** make send at-most-once across a post-send commit failure — `routes.py`

### Batch 5 — Scheduling / recurrence correctness
- [x] **G1 (HIGH):** clamp monthly day-of-month to ≤28 — `recurrence.py`
- [x] **G2 (HIGH):** reject numeric day-of-week in raw-cron passthrough — `recurrence.py`
- [x] **G3 (HIGH):** triage cron honours `settings.timezone` — `jobs.py`

### Batch 6 — Resource leaks
- [x] **H1 (HIGH):** close Telegram `Bot` httpx pools via `async with` (shared helper) — `lib.py`, `jobs.py`

Medium/Low items remain tracked in the artifact for a later pass.

---

## Critical

### Claude session transcripts committed & pushed to the PR branch
- **Where:** `api/app/workflows/code_issue.py:57`, `tools/github/runner.py:46-52`, `sandbox.py:43`
- **Problem:** `session_dir = os.path.join(worktree, "claude-home")` puts Claude's `~/.claude`
  state inside the git worktree; `commit_all()` runs `git add -A` then `push`, staging and
  pushing the entire `claude-home/` tree (session `*.jsonl` transcripts). Nothing git-ignores it.
- **Impact:** Every run leaks the full agent transcript (untrusted issue text, every file read
  incl. secrets/`.env`, all command output, model reasoning) into git history on the remote.
- **Fix:** Place `session_dir` outside the worktree, or `.git/info/exclude` it and scope commits;
  verify nothing under the session dir is ever staged.

---

## High

### Coding-agent sandbox: OAuth token in container env, exfiltrable via issue-driven Bash
- **Where:** `tools/github/sandbox.py:48, 81, 93`
- **Fix:** Don't put the token in the container's general env (use short-lived cred / mounted-then-removed
  file); run with `--network none` or an egress proxy so an exposed token can't leave.

### Event-loop blocking: sync LLM/Gmail I/O on the shared loop (5 sites)
- **Where:** `routes.py:276, 368, 447, 502-518`, `agent/toolkit.py:103-109`
- **Fix:** Wrap blocking calls in `await asyncio.to_thread(...)` (do I/O outside the open DB session);
  make `run_gmail_triage` an async tool. Mirror `routes.py:577` / `jobs.py:42`.

### SQLite: no WAL, no busy_timeout → "database is locked"
- **Where:** `store/db.py:175`, `store/observability.py:113`
- **Fix:** `PRAGMA journal_mode=WAL` + `PRAGMA busy_timeout=5000` on both engines.

### Auto-draft LLM calls run inside an open write transaction
- **Where:** `tools/gmail/pipeline.py:118-138`
- **Fix:** Generate draft bodies before opening the write transaction (or short per-email txns).

### Triage dedup TOCTOU race across cron / manual / chat
- **Where:** `pipeline.py:67-74,118-124`, `routes.py:699-705`, `toolkit.py:104`
- **Fix:** Funnel triage through one job id (so `max_instances=1` applies) or guard with a lock;
  catch per-row `IntegrityError` to make insert idempotent.

### Prompt-injection judge bypassed by paraphrase (heuristic is the sole gate)
- **Where:** `tools/gmail/service.py:31-48`, `injection.py:62-93`
- **Fix:** Run the LLM judge on all non-malicious new emails, not just heuristic-borderline.

### Prompt-injection judge failure is fail-OPEN (contradicts docstring)
- **Where:** `tools/gmail/service.py:46-48`, `injection.py:127-128`
- **Fix:** On judge exception, quarantine all borderline emails (`reason="judge_unavailable"`).

### `API_TOKEN` defaults to "" with no startup guard → fail-open auth
- **Where:** `config.py:99-100`, `routes.py:114-117`
- **Fix:** Reject blank/placeholder `API_TOKEN` at startup; reject empty configured token in `require_auth`.

### Send happens before the DB commit → duplicate-send window
- **Where:** `routes.py:502-522`
- **Fix:** Persist intent + commit, send, commit SENT; guard at-most-once on `gmail_draft_id`;
  surface "already sent — do not retry" on a post-send commit failure.

### Monthly reminders on the 29th–31st silently skip short months
- **Where:** `tools/reminders/recurrence.py:43-44`
- **Fix:** Clamp day-of-month to ≤28 (or use `day='last'`), or reject >28 with a clear message.

### Raw-cron passthrough accepts numeric day-of-week → off-by-one
- **Where:** `tools/reminders/recurrence.py:52-57`
- **Fix:** Reject a digit-containing DOW field (or translate to names) in the raw branch.

### Gmail triage cron ignores `settings.timezone`
- **Where:** `scheduler/jobs.py:194-203`
- **Fix:** `AsyncIOScheduler(timezone=settings.timezone)` or pass `timezone=` to the trigger.

### `notify()` leaks a Telegram Bot httpx pool on every call
- **Where:** `workflows/lib.py:51`, `scheduler/jobs.py:65,80,108`
- **Fix:** Use `async with Bot(token) as bot:` via a shared helper.

(The remaining High findings are the per-unit duplicates of the event-loop-blocking and
SQLite-WAL items above — same root causes surfaced by multiple reviewers.)

---

## Medium (reviewer-flagged; not all independently re-verified)

- `routes.py` is a 700-line function — 25+ routes + models + serializers as nested closures; split into `APIRouter` modules — `routes.py:111-708`
- save_to_gmail/send_draft near-duplicate; attachment-JSON parse copy-pasted 4× — `routes.py`
- Inconsistent exception→HTTP mapping across draft routes — `routes.py:274-379`
- Workflow never sets `CodingStatus.FAILED`; failed runs stuck RUNNING — `code_issue.py:65-153`
- Worktrees never cleaned up; re-run breaks `create_branch` — `code_issue.py:56-64`
- Inngest dev port 8288 bound to all interfaces — `docker-compose.yml:17-26`
- `current_run_id` ContextVar not propagated into triage worker thread — `jobs.py:40-42`
- Obs DB lazy session-factory init race → `TypeError` — `observability.py:102-117`
- Reminder create/cancel split commit + scheduler registration (partial-failure orphans) — `reminders/service.py:45-68`
- `_prune_old_logs` ISO-vs-space timestamp string compare — `observability.py:148-160`
- Neither engine enables WAL (dup of B1) — `db.py:170-179`
- Blocking Gmail I/O while a DB session is held — `routes.py:473-522`
- `RefreshError` unhandled in send/draft paths — `routes.py:436-511`
- `fetch_unread`/`build_query` don't filter `is:unread` — `gmail/client.py:33-155`
- HTML-comment injection heuristic dead (only text/plain screened) — `injection.py:40-91`
- key-sender rule overrides excluded-topic (contradicts priority) — `classifier.py:129-135`
- `max_tokens` cap applied only to Anthropic; Gemini/Groq uncapped — `llm/provider.py:122-144`
- `run_log`/`llm_usage` grow unbounded; full log text stored — `observability.py:148-161`
- Full root-logger output captured unredacted into run logs, shown in dashboard — `logging_setup.py:30-224`
- Scheduler job persisted before reminder row committed (orphan job) — `reminders/service.py:46-54`
- Manual triage unique job id bypasses cron `max_instances=1` (dup of B3) — `jobs.py:197-203`
- RSC pages throw on API failure, no error boundary — `web/app/email/runs/page.tsx:6-9`
- Email detail page reports any backend failure as 404 — `web/app/email/[id]/page.tsx:24-29`
- Logs search fires a request per keystroke (no debounce) — `web/components/logs-explorer.tsx:135-164`
- Concurrent log reloads have no sequencing guard — `web/components/logs-explorer.tsx:156-164`
- Email/draft timestamps parsed as local, not UTC — `web/lib/view/email.ts:74-75`, `draft.ts:48`

## Low / Nit (39)

See the artifact for the full list. Highlights: non-constant-time bearer compare (downgraded to
nit), unbounded `limit` params, missing indexes on `emails`/`llm_usage.run_id`, no Gmail retry/backoff,
References-header substring dedup, `extract_text` silent-empty, `UsageCallback` leak on LLM error,
`get_agent()` lazy-init race, command-palette focus trap, `getRun(id)` unencoded URL interpolation,
dead `revalidatePath` calls, several un-memoized web computations and uncleaned timers.
