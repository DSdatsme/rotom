# rotom — Implementation Plan

Detailed plan for everything that remains, in build order. Companion to `TODO.md`
(the checklist); this file says **how** each item gets built — files, approach,
acceptance criteria. Update both as work lands.

Current state (shipped): Telegram chat agent (LangGraph `create_react_agent` +
AsyncSqliteSaver checkpointing) · Gmail triage across 5 accounts (hour-granular
lookback, dedup ledger, rule-based skip pre-LLM, batched classification, auto-drafts
for needs_reply) · conversational draft composer · compact Telegram digest with dashboard deep links · reminders &
NL scheduling (APScheduler date/cron, dashboard countdown tiles + chat bar) ·
user-defined workflows on self-hosted Inngest (Python functions, cron + manual
triggers, run dashboard :8288) · Next.js dashboard (filters, bulk status, email
detail, draft edit/send/discard — send is the HITL gate) · swappable LLM providers
(Gemini/Groq/Anthropic, per-role routing) · APScheduler cron · FastAPI with bearer auth · CI (pytest + next build).

**Two execution engines, by design:** LangGraph drives the *conversational* path
(Telegram chat — open-ended, model picks which tools to chain); Inngest drives the
*deterministic* path (scheduled/triggered workflows — fixed step pipelines with
retries). They share only `get_chat_model` (the LLM provider factory). Keep them
separate — neither's strength (chat-thread checkpointing vs. batch durability) fits
the other's job. APScheduler still owns the triage + reminder crons (migrating those
onto Inngest is a deferred, optional TODO).

---

## Phase 0 — Polish & hygiene (near-term)

### 0.1 Gemini key — RESOLVED
- The `AQ.` key is permanent (confirmed by owner); no swap needed.

### 0.2 Mark triaged mail in Gmail (labels)
- **Goal:** inboxes reflect triage — every processed email gets an `AI-Processed`
  label; optionally `rotom/critical`, `rotom/needs-reply` per category.
- **Approach:**
  - Add `gmail.modify` to `SCOPES` in `api/app/tools/gmail/client.py` — this
    **requires re-running `auth_setup.py` for all 5 accounts** (one-time; new
    refresh tokens because scopes are baked into the grant).
  - `GmailAccount.ensure_label(name) -> label_id` — `users().labels().list/create`,
    cache ids per instance.
  - `GmailAccount.add_labels(message_id, label_ids)` — `users().messages().modify`.
  - Pipeline step 4.5: after storing, label each new email (failure degrades into
    `result.errors`, never blocks storing).
  - Config: `GMAIL_APPLY_LABELS=true`, `GMAIL_LABEL_PREFIX=rotom`.
- **Files:** `tools/gmail/client.py`, `tools/gmail/pipeline.py`, `config.py`, `.env*`.
- **Done when:** a triage run labels new mail in all accounts; label failures show
  as ⚠ lines in the digest.

### 0.3 Provider quota fallback (smart retry)
- **Goal:** a 429/quota error on Gemini auto-falls back to Groq (then Anthropic if
  keyed) instead of failing the run.
- **Approach:**
  - `llm/provider.py`: `get_chat_model_chain(role) -> list[BaseChatModel]` built
    from `FALLBACK_ORDER = ["gemini", "groq", "anthropic"]` filtered to providers
    with keys; primary stays whatever the role's model string says.
  - `llm/resilient.py`: `invoke_with_fallback(chain, fn)` — try each model; catch
    quota/rate errors (google `ResourceExhausted`, httpx 429, groq rate-limit) with
    1 retry + exponential backoff before falling to the next provider; re-raise
    anything non-quota immediately.
  - Classifier and drafter call through the wrapper. Log which provider served.
- **Caveat:** structured-output behavior differs per provider — keep the existing
  `BatchClassification` schema (works on Gemini and llama-3.3-70b; never use
  llama-3.1-8b-instant, it emits malformed tool calls).
- **Files:** `llm/provider.py`, new `llm/resilient.py`, `tools/gmail/classifier.py`,
  `tools/gmail/drafter.py`.
- **Done when:** simulated 429 (monkeypatched test) falls through to the next
  provider and the digest notes degraded mode.

### 0.4 Sent/discarded drafts archive view
- **Goal:** dashboard tab for past drafts (API already supports `?status=`).
- **Approach:** tabs on `/email/drafts` — Pending | Sent | Discarded — via
  `searchParams.status`; sent drafts show `sent_at`; read-only cards (no
  Edit/Send/Discard buttons for non-pending).
- **Files:** `web/app/email/drafts/page.tsx`, `web/lib/api.ts` (`getDrafts(status)`
  already exists — verify it passes through), small `DraftTabs` client component.
- **Done when:** all three tabs render correct lists; pending tab unchanged.

### 0.5 Email retention / cleanup
- **Goal:** DB doesn't grow forever; skip-category rows purged after N days.
- **Approach:**
  - Config: `EMAIL_RETENTION_DAYS=30` (skip rows), `0` = keep forever.
  - `store/cleanup.py`: delete `emails` where `category='skip' AND created_at < cutoff`
    (cascade drafts — skip never has drafts, assert anyway); keep `processed_messages`
    ledger forever (it's the dedup guarantee and is tiny).
  - Scheduler: daily job `email-cleanup-cron` at 04:00, same jobstore pattern as
    `scheduled_gmail_triage_job` (module-level argless function for picklability).
- **Files:** new `store/cleanup.py`, `scheduler/jobs.py`, `config.py`.
- **Done when:** job registered at boot; old skip rows removed; ledger intact.

### 0.6 Per-account auto-draft toggle
- **Goal:** draft replies for work accounts, skip drafting for noisy ones.
- **Approach:** `GMAIL_DRAFT_ACCOUNTS=main,work` (empty = all). Pipeline
  checks `e["account"] in draft_accounts` before calling `draft_fn`.
- **Files:** `config.py`, `tools/gmail/pipeline.py` (pass allowed set in), `service.py`.
- **Done when:** needs_reply mail in a non-listed account is stored without a draft.

### 0.7 docker-compose end-to-end check
- **Goal:** the stack has only run as bare processes; prove `docker compose up` works.
- **Steps:** build both images → verify `data/` volume mount + `env_file` wiring →
  bot answers on Telegram → dashboard at :3000 talks to api at :8000 (compose
  network: `API_URL=http://api:8000` for web) → one triage run persists across
  `docker compose restart`.
- **Files:** `docker-compose.yml`, possibly `web/Dockerfile` (needs `API_URL` env),
  README run instructions.
- **Done when:** full loop (Telegram → triage → digest → dashboard → send) works
  inside compose.

---

## Phase 1 — Reminders & natural-language scheduling (Iteration 2) — SHIPPED

The first new tool family after Gmail. Scheduler infra already exists.
Shipped: Reminder model + date/cron jobs with boot reconciliation, agent tools
(get_current_time + create/list/cancel), NL parse → confirm gate, dashboard
countdown tiles + "+" form + chat bar, recurrence shorthands ("everyday",
"every monday") normalized to cron without LLM. Note: generated/LLM crons must
use day NAMES — APScheduler reads numeric DOW as 0=Monday (standard cron: 1=Monday).

### 1.1 Data model + scheduling
- `store/db.py`: `Reminder(id, text, fire_at, recurrence_cron nullable,
  status: pending|fired|cancelled, created_at)` + `_migrate()` entry.
- `scheduler/jobs.py`: `schedule_reminder(reminder_id)` registers an APScheduler
  `date` trigger (one-time) or `cron` trigger (recurring), job id `reminder-{id}`.
  Module-level `fire_reminder_job(reminder_id)` loads the row, sends Telegram
  message ("⏰ Reminder: …"), marks status=fired (recurring stays pending).
- Boot reconciliation: on startup re-register jobs for pending reminders whose job
  is missing from the jobstore (covers jobstore wipe).

### 1.2 Agent tools
- `agent/toolkit.py`: `create_reminder(text, when_iso, recurrence_cron="")`,
  `list_reminders()`, `cancel_reminder(id)`.
- **Time parsing stays in the LLM**: the chat model converts "tomorrow 3pm" to ISO
  in the tool call; the system prompt gets current datetime + timezone
  (`TIMEZONE=Asia/Kolkata` config) so it resolves relative dates correctly. Tool
  validates `fire_at` is in the future and returns a confirmation string the agent
  echoes ("Reminder set for Sat Jun 8, 3:00 PM").
- Guardrail: reminders are read/write-local actions — no HITL gate needed, but cap
  at `MAX_ACTIVE_REMINDERS=100`.

### 1.3 API + dashboard
- `api/routes.py`: `GET /api/reminders?status=`, `DELETE /api/reminders/{id}`.
- `web/app/reminders/page.tsx`: list (text, next fire, recurrence badge), cancel
  button (inline action like `discardDraftInline`); sidebar entry "Reminders".
- **Done when:** "remind me to call Mom tomorrow 3pm" → confirmation in chat → row
  in dashboard → Telegram message fires at 3pm (verify with a 2-minute reminder)
  → recurring "every monday 9am standup notes" survives an API restart.

---

## Phase 1.5 — User-defined workflows — SHIPPED (on Inngest)

Built on self-hosted Inngest instead of the YAML engine sketched earlier — see
docs/superpowers/specs/2026-06-07-workflows-inngest-design.md and docs/workflows/.
Workflows are Python functions (one file each in api/app/workflows/) with cron +
manual-event triggers, per-step retries, and the Inngest dashboard (:8288) for run
history. Helpers in app/workflows/lib.py (llm / run_script / notify) are the seam
where guardrails land.

Deferred TODOs:
- [ ] Guardrails in lib.py: max_llm_calls per run, script allow-list config,
      secret-scrubbed step logs
- [ ] External-write steps (GitHub issues, posts) — needs policy layer (5.2);
      Inngest waitForEvent enables HITL approval steps
- [ ] rotom-dashboard view of run history (Inngest REST API)
- [ ] Production signing keys + inngest data backup story; full compose e2e
- [ ] Migrate gmail-triage / reminder crons onto Inngest (decide later)

## Phase 2 — HITL approve-to-send from Telegram (Iteration 3)

Today drafts can only be sent from the dashboard. Add Telegram inline buttons.

### 2.1 Draft notification with buttons
- After auto-draft creation, send per-draft Telegram message: original subject/sender,
  draft body (chunked if long), `InlineKeyboardMarkup` with ✅ Approve · ✏️ Edit ·
  ⏭ Skip (`callback_data: "draft:{id}:approve|edit|skip"`).
- `channels/telegram.py`: `CallbackQueryHandler` with owner-chat-id guard (same
  filter as messages).

### 2.2 Actions
- **Approve** → reuse the exact send path the dashboard uses (`send_reply` with
  threading headers + mark draft sent) — *one* send implementation, the approval
  click is the HITL gate. Edit message in place to "✅ Sent".
- **Skip** → mark draft discarded, edit message to "⏭ Skipped".
- **Edit** → reply "Send me your corrections"; store `awaiting_edit[chat] = draft_id`
  (LangGraph interrupt or a simple pending-state table — start with a
  `draft_edit_requests` row keyed by chat, simpler than graph interrupts);
  next user message regenerates via drafter with the correction appended, posts
  the new draft with fresh buttons.
- Config: `TELEGRAM_DRAFT_NOTIFICATIONS=true` (off = digest-only, today's behavior).
- **Done when:** full Approve flow sends a threaded reply from a real account;
  Skip discards; Edit → correction → new draft → Approve works end-to-end.

---

## Phase 3 — More tools (Iteration 4)

Each tool family follows the Gmail pattern: `tools/<name>/` package, deterministic
service functions, agent tools in `toolkit.py`, API routes, dashboard section,
external-send actions always HITL-gated.

### 3.1 GitHub track — decomposed (brainstormed 2026-06-08)

The GitHub work split into independent features during brainstorming:
- **F0 — foundation:** thin `gh`/`git` helpers (built as part of F2; no standalone REST
  client needed — `gh` CLI covers V1).
- **F1 — issue creation from chat** (gated write): separate, later.
- **F2 — coding agent** ⭐ — DESIGNED + PLANNED, see below.
- **F3 — repo activity watch:** separate, later.

Earlier sketch (notifications digest, PR summaries, `create_issue`/`merge_pr`) folds into
F1/F3 + reads the coding agent needs; revisit per-feature.

### 3.4 Coding agent (F2) — DESIGNED + PLANNED (ready to build)

Full design: `docs/superpowers/specs/2026-06-08-coding-agent-design.md`.
Implementation plan: `docs/superpowers/plans/2026-06-08-coding-agent.md`.

Decided design (supersedes the Aider/mini-swe-agent sketch below):
- **Engine:** Claude Code headless via `CLAUDE_CODE_OAUTH_TOKEN` (subscription; separate
  Agent-SDK credit pool — no API key, doesn't touch the Gemini/Groq budget).
- **Orchestration:** an Inngest workflow (`code_issue`) — Inngest orchestrates, it does
  NOT isolate.
- **Isolation:** every Claude run (coder + reviewers) executes in an ephemeral
  `docker run --rm` container (worktree-only mount, native CC sandbox inside, gh token
  stays host-side, non-root + caps). No host pollution. **Docker is the security boundary.**
- **Multi-agent:** coder (full context, resumable session) → bounded CI-fix loop
  (`gh pr checks` → resume coder on red, ≤`MAX_FIX_ROUNDS`) → fresh read-only reviewer +
  security agents over the diff → findings posted as a PR comment.
- **Gate:** draft PR only; never default branch; never merge — the human merge is the gate.
  Allow-listed repos + push-access check (fork flow is V2).
- **Resumability groundwork:** persistent per-issue worktree (`data/coding/<org>/<repo>/<issue>`)
  + `CodingRun` table storing `claude_session_id`.
- V2 deferred: reviewer self-repair, mid-run pause/fix UI, fork-based PRs, GitHub webhooks
  (replace CI polling), network egress filtering, the dashboard runs view (now folded into
  the Observability section in TODO.md).

### 3.4-legacy Coding agents (original sketch — superseded by 3.4 above)
- Scope: "fix issue #N in repo X" → spawn Aider (or mini-swe-agent) in a sandboxed
  workdir → branch → commit → push → open PR → report PR link in chat.
- Hard bounds: allow-listed repos (`CODING_AGENT_REPOS`), max runtime, never push
  to default branch, PR is the HITL gate (human merges).

### 3.2 Linear (`tools/linear/`)
- Auth: `LINEAR_API_KEY`, GraphQL endpoint via `httpx`.
- Tools: `create_linear_issue(title, desc, team, priority)` (write-local, confirm
  echo), `list_linear_issues(filter)`, `sprint_backlog()`.
- Dashboard: `/linear` — backlog table grouped by state.

### 3.3 Twitter/X draft-and-post
- Tools: `draft_tweet(topic)` → stored in a generic `posts` table
  (platform, body, status pending/posted/discarded) — same lifecycle as email drafts.
- Posting is **dashboard-only or Telegram-approve** (HITL gate identical to email
  send). API: `POST /api/posts/{id}/publish`.
- Auth: X API v2 user-context OAuth; keep behind `TWITTER_ENABLED` flag since API
  access tiers change.

### 3.4 Coding agents (bounded)
- Scope: "fix issue #N in repo X" → spawn Aider (or mini-swe-agent) in a sandboxed
  workdir → branch → commit → push → open PR → report PR link in chat.
- Hard bounds: allow-listed repos (`CODING_AGENT_REPOS`), max runtime, never push
  to default branch, PR is the HITL gate (human merges).
- Runs as a subprocess job through the scheduler (long-running); progress messages
  to Telegram.
- This is the riskiest item — build last in this phase, behind `CODING_AGENTS_ENABLED`.

---

## Phase 4 — Memory & channels (Iteration 5)

### 4.1 Long-term memory
- Start with **sqlite-vec + a `memories` table** (text, kind: preference|contact|fact,
  embedding, created_at) before reaching for Mem0 — keeps the single-file-DB promise.
- Embeddings: Gemini `text-embedding-004` (already keyed).
- Write path: agent tool `remember(text, kind)` + automatic extraction pass after
  conversations (batched, cheap model).
- Read path: top-k similar memories injected into the agent system prompt per turn;
  drafter gets communication-style memories.
- Postgres+pgvector migration only if/when sqlite-vec hits limits.

### 4.2 WhatsApp channel
- `channels/whatsapp.py` behind the same interface as Telegram (define a small
  `Channel` protocol first: `send(text)`, `register_handler(fn)` — refactor
  telegram.py to it).
- Evolution API (self-hosted) or WhatsApp Cloud API; chat threads map to the same
  LangGraph thread keying.

### 4.3 Voice notes
- Telegram already delivers voice files: download OGG → STT (Groq Whisper
  `whisper-large-v3` — already keyed, fast, cheap) → feed transcript into the
  normal agent path; prefix reply with "🎙 heard: …" for confirmation.

---

## Phase 5 — Guardrails (prompts & actions)

Build alongside Phases 1–3, not after. Order within phase:

### 5.1 Injected-prompt detection per email — SHIPPED

Spec: `docs/superpowers/specs/2026-06-08-injection-detection-design.md` · Docs: `docs/guardrails/`

- `tools/gmail/injection.py`: `score_injection(subject, body) -> (score, flags)` —
  heuristics: instruction patterns ("ignore previous", "you are now", "system:"),
  role markers, zero-width/RTL unicode, base64 blobs > N chars, HTML comments
  with instructions.
- Score ≥ threshold → email flagged `suspicious=true` (new column), **never
  auto-drafted**, ⚠ badge in digest + UI; borderline band sent to a batched LLM
  judge (`classify` role) with a yes/no schema; fail-safe default quarantines on
  missing verdict.
- Adversarial fixture tests: `tests/fixtures/injection/*.txt` corpus run in CI.

### 5.2 Central action policy layer
- `agent/policy.py`: every tool registered with `ActionClass = READ | WRITE_LOCAL |
  EXTERNAL_SEND`. A decorator enforces: EXTERNAL_SEND tools cannot be called by the
  agent at all (raise + Telegram anomaly alert); WRITE_LOCAL gets rate limits.
- Today this is true by construction (no send tool exists in the agent toolkit);
  the policy layer makes it true **by enforcement** so Phase 3 tools can't regress it.
- Per-tool rate limits: token bucket in SQLite (`tool_calls` table) —
  `max drafts/day`, `max triage runs/hour`, configurable.

### 5.3 Output validation
- `llm/output_guard.py`: checks on drafts/replies before storing — no secrets
  (regex for key shapes: `AIza`, `gsk_`, `1//`, bearer-like strings), no URLs not
  present in the source email, length bounds. Violations → draft rejected, logged,
  ⚠ in digest.

### 5.4 Spend guardrail
- Track per-call token usage (LangChain callbacks) into a `llm_usage` table;
  daily budget `LLM_DAILY_TOKEN_BUDGET`; on breach → halt non-chat LLM calls
  (triage pauses), alert on Telegram.

### 5.5 Dry-run mode + anomaly alerts
- `DRY_RUN=true` → all WRITE_LOCAL/EXTERNAL_SEND service functions log instead of
  executing (inject a no-op transport, don't sprinkle ifs).
- Policy denials and guard rejections always alert to Telegram — denied actions
  visible, never silent.

---

## Phase 6 — Infra / ops

- **CI (do early, it's cheap):** GitHub Actions — `uv run pytest` + `npm run build`
  on push; later add the injection fixture suite.
- **Deploy to always-on box:** VPS/homelab, docker compose from Phase 0.7;
  secrets via env injection (not committed `.env`); `restart: unless-stopped`.
- **Backups:** nightly `sqlite3 .backup` of `data/` to object storage or a second
  disk; test restore once.
- **Structured logging + error alerting:** JSON logs; unhandled exceptions in
  scheduler jobs / bot handlers → Telegram alert (reuse digest ⚠ pattern).
- **Postgres migration:** only when memory layer or multi-instance demands it —
  SQLAlchemy means it's a `DATABASE_URL` swap + alembic baseline.
- **Retire gmail-summarizer cron** once rotom runs 24/7 (don't disable its GCP
  client before then — the old GH Actions cron still uses it).
- **API rate limiting:** slowapi or simple middleware token bucket on FastAPI;
  audit-log table for sends (drafts already have `sent_at` — add a UI view).

---

## Suggested build order

```
0.1 Gemini key (user) ─┐
0.2 Gmail labels       ├─ Phase 0 polish (parallelizable, small)
0.4 drafts archive     │
0.5 retention          │
0.6 draft toggle       ┘
6.x CI                 ── early, protects everything after
1.x Reminders          ── SHIPPED
1.5 Workflows          ── SHIPPED (Inngest)
5.1 injection detect   ── SHIPPED
3.4 Coding agent (F2)  ── DESIGNED + PLANNED, ready to build (Claude Code + Inngest + Docker)
0.3 quota fallback     ── before triage volume grows
2.x Telegram approve   ── biggest UX win for daily use
5.2 policy layer       ── prerequisite for Phase 3 write tools + workflow send steps
3.1 GitHub F1/F3 → 3.2 Linear → 3.3 Twitter
0.7 compose e2e → 6 deploy ── once daily-driver stable
4.x memory + WhatsApp + voice
observability          ── brainstorm + build (folds in run-history/usage views)
```

## Standing rules (apply to every phase)

- Agent **never** performs external sends — approval click (dashboard or Telegram
  button) is always the gate; new tools must register with the policy layer (5.2).
- All external content (emails, GitHub comments, issue bodies) is untrusted —
  wrap in delimiter tags as DATA, never instructions.
- Secrets only in gitignored `.env` files / deployment env — never committed.
- Per-source failures degrade (⚠ in digest), never kill a run.
- Every schema change goes through `_migrate()` in `store/db.py` (PRAGMA + ALTER).
- Keep everything swappable: providers behind `get_chat_model`, channels behind a
  protocol, DB behind SQLAlchemy.
