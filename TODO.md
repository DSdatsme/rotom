# rotom — TODO

Iteration 1 (shipped): Telegram chat agent · Gmail triage (5 accounts, 2-day lookback) ·
auto-drafted replies · Conversational draft composer · Next.js dashboard with human-gated send · swappable LLM providers
(Gemini / Groq / Anthropic, per-role routing).

## Near-term (polish what exists)

- [x] **Gemini key** — `AQ.` key confirmed permanent by owner (no expiry action needed)
- [x] **Set a real `API_TOKEN`** — random 64-hex token in `.env` / `api/.env` / `web/.env.local`
- [x] **Digest formatting** — FYI/skip collapse into counts; critical/needs_reply link
      straight to dashboard email detail pages; excluded topics rule-skipped pre-LLM;
      lookback window now hour-granular (`GMAIL_TRIAGE_LOOKBACK_HOURS`)
- [ ] **Smart quota management** — auto-fallback between providers on 429/quota errors
      (Gemini → Groq → Anthropic); retry with backoff in classifier/drafter
- [ ] **Sent-draft archive view** — dashboard tab for sent/discarded drafts (API already
      supports `?status=`)
- [ ] **Email retention/cleanup** (see PLAN.md §0.5) — scheduled job that purges old
      triaged emails after a configurable window (`EMAIL_RETENTION_DAYS`; `0` = keep
      forever). Default to purging `skip`/`fyi` aggressively and keeping
      critical/needs_reply longer; never touch the `processed_messages` dedup ledger
      (tiny, and it's the replay guard). Also: a **one-off purge of the ~137 stale rows**
      from the first no-date-filter triage run (09:38 UTC 2026-06-07, ages up to 89d) —
      either via the new job's first pass or a manual cleanup.
- [ ] **Per-account toggle for auto-drafting** — drafting replies makes sense for work
      accounts, less for noisy ones
- [ ] **docker-compose end-to-end check** — images build but full stack hasn't been run
      via compose yet (volume paths, env_file wiring)
- [ ] **Review [odysseus](https://github.com/pewdiepie-archdaemon/odysseus) in detail** —
      revisit the reference repo end-to-end (we borrowed injection-hardened prompts,
      degraded-state digest reporting, and its triage UX). Mine it for more patterns worth
      porting (categories, prompt structure, anything reusable for the draft composer).

## Iteration 2 — Reminders & scheduling (from blueprint) — SHIPPED

- [x] Natural-language reminders via chat ("remind me to call Mom tomorrow 3pm")
- [x] APScheduler `date` trigger jobs (one-time) + `cron` (recurring) + boot reconciliation
- [x] Agent tools: `create_reminder`, `list_reminders`, `cancel_reminder`, `get_current_time`
- [x] Reminder fire → Telegram message
- [x] Dashboard section: countdown tiles, + add form, NL chat bar with confirm gate

## Iteration 2.5 — User-defined workflows — SHIPPED (Inngest; see PLAN.md §1.5)

- [x] Workflows as Python functions on self-hosted Inngest (YAML approach dropped)
- [x] Run history/stats via Inngest dashboard (:8288)
- [x] Cron + manual event triggers (`TriggerCron` + `TriggerEvent("workflows/<name>.requested")`)
- [x] `run_workflow` agent tool — fires internal event, results arrive on Telegram
- [x] Helpers in `lib.py`: `llm`, `run_script`, `notify` — seam for future guardrails
- [ ] Guardrails in lib.py: max_llm_calls per run, script allow-list config, secret-scrubbed step logs
- [ ] External-write steps (GitHub issues, posts) — needs policy layer (5.2); Inngest waitForEvent enables HITL approval steps
- [ ] rotom-dashboard view of run history (Inngest REST API)
- [ ] Production signing keys + inngest data backup story; full compose e2e
- [ ] Migrate gmail-triage / reminder crons onto Inngest (decide later)

## Iteration 3 — HITL approve-to-send from Telegram (from blueprint)

- [ ] Draft notification with inline Approve / Edit / Skip buttons in Telegram
- [ ] Approve → send via Gmail directly from chat (today send is dashboard-only)
- [ ] Edit → reply with corrections, agent regenerates (LangGraph interrupt + resume)

## Iteration 4 — More tools (from blueprint)

- [ ] **GitHub** (`tools/github/`): notifications digest, PR list/review summaries,
      create issues, approve/merge PR with HITL gate; dashboard section
- [ ] **Linear** (`tools/linear/`): create/update issues from chat (GraphQL, API key),
      read sprint backlog; dashboard section
- [ ] **Twitter/X**: draft tweet from chat → review/post via HITL gate
- [ ] **Coding agents** (Aider / mini-swe-agent): bounded issue → branch → PR flow
- [ ] **Push notifications via ntfy.sh** (`channels/` — pluggable `NotificationChannel`
      layer): add **ntfy** alongside the existing **Telegram** channel.
      📄 Spec: `docs/superpowers/specs/2026-06-14-notify-channels-design.md` ·
      Plan: `docs/superpowers/plans/2026-06-14-notify-channels.md`
  - [ ] **v1 — notify plumbing + ntfy channel (spec'd + planned TDD; ready to execute).** A general
        `notify(text, *, channel="telegram", title=None)` seam (`channel` ∈ telegram/ntfy/both)
        backed by a `NotificationChannel` Protocol (Telegram + ntfy impls); refactor the
        scattered Telegram sends (`workflows/lib.py`, scheduler digest + failure alert,
        `fire_reminder_job`) onto it — behavior unchanged unless a caller opts into ntfy.
        Config `NTFY_BASE_URL`/`NTFY_TOPIC`/`NTFY_TOKEN`. Usable from any workflow stage, not
        just reminders. **Note:** the free topic is unprotected/world-readable → keep ntfy
        pushes terse + non-sensitive.
  - [ ] **v2 — routing & priority.** `priority` field (low/default/urgent) + ntfy priority
        mapping (low→2, default→3, urgent→5) + Telegram silent-send for low; **urgent →
        auto-include ntfy** escalation; per-reminder `channel`+`priority` columns + NL parser
        keywords + dashboard add-form selector + parse-confirmation display; generalized
        per-event-type routing policy.
  - [ ] **v2 — ntfy hardening & extras.** Protected / less-guessable topic (require
        `NTFY_TOKEN`); `Tags`/emoji, `Click` deep-link back to the dashboard, reminder titles.
- [x] **Calendar v1 — dashboard week view** (`tools/calendar/`): merged read-only week grid
      across all Gmail-linked accounts' primary calendars, live-fetched from the Calendar API
      (no caching/sync job). Scope granted is `calendar.events` (read/write), so Calendar V2
      needs no further re-auth. Spec:
      `docs/superpowers/specs/2026-07-25-calendar-integration-design.md`.
  - [ ] **Calendar V2** — create/update events from chat with a HITL gate (if event
        titles/locations are ever fed to an LLM — folded into a digest or exposed as a chat
        tool — they must go through the same untrusted-content fencing as email; event data is
        attacker-influenceable, anyone can send a calendar invite); secondary/shared calendars
        beyond each account's primary; per-account opt-out; fold today's agenda into the
        Telegram digest or expose it as a chat tool.
    - [ ] Multi-day events (start before the displayed week, end during/after it, e.g. a trip)
          are currently dropped entirely from the grid — not just simplified to their start day
          as originally intended. Worth a clamp-to-week-start fix or at least a "N more"
          indicator.
    - [ ] Per-account Calendar API fetches are sequential with no timeout; a hung account
          stalls the whole page load. Worth `asyncio.gather`-ing the per-account fetches and
          adding a per-account timeout.
    - [ ] Raw provider exception strings (e.g. `invalid_scope: Bad Request`) go straight into
          the error banner; mapping known errors to an actionable message (e.g. "run
          `auth_setup.py <account>` again") would help.
    - [ ] Overlapping same-day timed events currently render fully-overlapping (no
          side-by-side/column layout) — fine for light days, not for busy merged calendars.

## Iteration 5 — Memory & channels (from blueprint)

- [ ] Long-term memory (Mem0 or sqlite-vec): preferences, contacts, communication style;
      inject relevant memories into agent prompt
- [ ] WhatsApp channel (`channels/whatsapp.py`, Evolution API) behind the same interface
      as Telegram
- [ ] Voice notes → STT → agent (Telegram already delivers voice messages)

## Observability — SHIPPED (see `docs/observability/`, spec `2026-06-09-observability-design.md`)

- [x] **Dashboard observability surface** — Runs list + detail under `/email/runs` (status,
      duration, tokens, latency, captured logs); `/observability` board.
- [x] **Usage metrics** — LLM token usage + latency per provider/model/role, per run and
      aggregated by model/day, with a tokens-over-time chart.
- [x] **Centralized logs explorer** (`/observability/logs`) — structured JSON logs persisted to
      `log_entry`, faceted (level/kind/run/text/time), live-tail, cursor pagination.
- [x] **Pluggable instrumentation seam** — `record_run(kind)` + `ObservabilitySink`/`QueryProvider`
      Protocols (factory off `OBSERVABILITY_BACKENDS`); a future external backend is a drop-in sink.
- [x] **Live refresh** — runs poll while `running`; client polling via server-side route proxies.

### Observability — remaining (next: unify run sources, spec `2026-06-10-unify-run-sources-design.md`)

- [ ] **Interrupted-run handling** — zombie `running` rows on crash/restart → new `interrupted`
      status + heartbeat + a 5-min reaper job (excludes Inngest).
- [ ] **Unify all run sources** under one `RunLog` — `source`/`parent_run_id` facets + automatic
      run→sub-run nesting (workflow→triage, coding-agent→sub-tasks).
- [ ] **First-class Inngest run tracking** — middleware-driven idempotent rows + status sync
      (today: link-only to the Inngest dashboard).
- [ ] **Tool-call counts** — per-run agent tool-call metrics (needs an agent-side hook).
- [ ] **Optional external provider** — ship traces/metrics/logs to BetterStack / Datadog / Loki
      via a new sink, if local SQLite is ever outgrown. (Earlier rejected Langfuse: ≈30-day free
      retention too short.)

## Infra / ops

- [ ] Deploy to always-on box (VPS or homelab) — currently dies with the laptop
- [ ] Postgres migration when needed (memory layer / multi-instance); SQLAlchemy makes
      this a `DATABASE_URL` swap
- [ ] Structured logging + error alerting to Telegram (beyond triage failures)
- [ ] Backup strategy for `data/` volume
- [ ] **Observability DB disaster recovery** — periodic *consistent* snapshot of
      `observability.db` (`sqlite3 … "VACUUM INTO …"` or the `.backup` API — never a live
      `cp`, WAL can tear) → versioned S3 bucket (`S3_BACKUP_BUCKET` + lifecycle rules); a
      nightly scheduler job. RPO ≈ snapshot interval. Generalize to the whole `data/` volume
      later. (Split out of the observability spec — telemetry retention is unlimited locally;
      this is only the off-box copy.)
- [x] CI: pytest (uv) + next build on push/PR — `.github/workflows/ci.yml`
- [ ] Retire the old gmail-summarizer-runner cron once rotom is deployed 24/7

## Guardrails (prompts & actions)

**Prompt guardrails**
- [x] **Injected-prompt detection per email** — heuristic scorer (`score_injection`) +
      batched LLM judge for the borderline band quarantine emails before classification;
      `suspicious` flag stored in DB; ⚠ badge in digest + dashboard; `?suspicious=`
      filter on the email list; quarantined emails are never auto-drafted
- [ ] Input sanitization layer before agent/classifier prompts — strip/neutralize
      instruction-like patterns in email content beyond the current delimiter tags
- [ ] Output validation — check agent replies and drafts against policy before they
      leave (no leaked secrets/PII, no URLs the user never saw, length/tone bounds)
- [ ] Jailbreak resistance tests — adversarial fixture suite (emails that try to make
      the agent reveal config, send mail, change behavior) run in CI
- [ ] System-prompt hardening review per tool added (each new tool widens the attack
      surface the prompt must constrain)

**Action guardrails**
- [ ] Central action policy: classify every agent tool as read / write / external-send;
      external-send always requires explicit human approval (today enforced by
      construction — make it enforced by a policy layer so new tools can't bypass it)
- [ ] Per-tool rate limits and daily caps (e.g. max drafts/day, max triage runs/hour)
- [ ] LLM spend guardrail — token/cost budget per day with alert + halt on breach
- [ ] Confirmation gates for irreversible actions (delete, merge, post) — reusable
      HITL primitive, not per-tool one-offs
- [ ] Dry-run mode — run any action with side effects in log-only mode for testing
- [ ] Anomaly alerts — notify on Telegram when the agent attempts something outside
      policy (denied actions should be visible, not silent)

## Security hardening

- [ ] Rate-limit FastAPI endpoints (bearer token is the only gate today)
- [ ] Audit log of sends (who/what/when — drafts table has sent_at, add UI)
- [ ] Secrets out of `.env` into a proper secret store when deployed
- [ ] Review prompt-injection defenses against real adversarial email samples

## Code review follow-ups — Medium (2026-06-21)

From the full review in `docs/research/2026-06-21-code-review.md` (artifact:
https://claude.ai/code/artifact/c9d45ff0-bdd4-4aef-ba0a-fa5fd13200e2). The Critical + all
High items are already fixed (branch merged from `fix/code-review-crit-high`). These Medium
items are reviewer-flagged but were NOT independently re-verified — confirm each against the
code before acting.

### API surface
- [ ] **Split `routes.py` (700-line `create_app`)** — `api/app/api/routes.py:111-708`.
      25+ routes + Pydantic models + serializers + helpers are nested closures in one
      function. Break into `APIRouter` modules by resource (emails, drafts, reminders,
      observability); lift models/serializers/`require_auth` to module scope.
- [ ] **De-duplicate draft send/save + attachment parsing** — `routes.py`. `save_to_gmail`
      and `send_draft` bodies are near-identical; attachment-JSON parsing is copy-pasted 4×.
      Extract a shared `_resolve_send_args(draft, email)` + `_selected_attachment_paths(draft)`.
- [ ] **Consistent exception→HTTP mapping on draft routes** — `routes.py:274-379`. Some paths
      raise raw 500s with exception text, others swallow into the chat thread. Pick one
      policy (clean 4xx/5xx, no raw exception text to client).

### Coding agent
- [ ] **Set `CodingStatus.FAILED` on failure** — `workflows/code_issue.py:65-153`. The
      workflow never marks FAILED, so crashed/errored runs stay `RUNNING` forever. Wrap the
      step body so terminal errors set FAILED (mirrors the BLOCKED path).
- [ ] **Clean up / reuse worktrees safely** — `code_issue.py:56-64`. Worktrees are never
      removed; a re-run on the same issue hits an existing dir and `create_branch` fails.
      Either reuse (git fetch + reset + checkout -B) or remove before clone.

### Concurrency / data (lower-severity than the High set, same families)
- [ ] **Propagate `current_run_id` into the triage worker thread** — `jobs.py:40-42`. The
      ContextVar isn't copied across `asyncio.to_thread`, so triage LLM usage + DB logs are
      unattributed to the run. Capture it and re-set inside the thread (or use
      `contextvars.copy_context().run`).
- [ ] **Guard obs-DB lazy session-factory init** — `store/observability.py:102-117`.
      Check-then-act on `_SessionFactory` can race across threads → `TypeError: 'NoneType'
      not callable`. Add a lock (same pattern as a future `db.init_db` guard).
- [ ] **Atomic reminder create/cancel** — `tools/reminders/service.py:45-68`. DB commit and
      scheduler registration can partially fail (orphaned job or orphaned row). Register the
      job only after the row commits, and remove the row if registration throws.
- [ ] **Fix `_prune_old_logs` timestamp comparison** — `store/observability.py:148-160`.
      Compares an ISO-with-offset string against space-separated/offset-less stored values,
      so pruning is unreliable. Normalize to a single stored format (UTC, ISO-8601).

### Gmail
- [ ] **Handle `RefreshError` in send/draft paths** — `routes.py:436-511`. A failed OAuth
      refresh surfaces as a 500; map to a clear 409/422 telling the user to re-run auth_setup.
- [ ] **`fetch_unread`/`build_query` actually filter `is:unread`** — `tools/gmail/client.py:33-155`.
      Names/docstrings say unread but the query doesn't constrain it; add `is:unread` (or rename).
- [ ] **Screen HTML bodies too (or drop the dead heuristic)** — `injection.py:40-91`. The
      HTML-comment injection pattern can never fire because only `text/plain` is screened.
      Either extract+screen `text/html`, or remove the dead branch.
- [ ] **Fix key-sender vs excluded-topic precedence** — `classifier.py:129-135`. Key-sender
      currently overrides excluded-topic, contradicting the documented "exclusions win" order.

### Observability / cost
- [ ] **Cap `max_tokens` for all providers** — `llm/provider.py:122-144`. The output cap is
      applied only to Anthropic; Gemini/Groq run uncapped. Apply per-provider.
- [ ] **Bound obs table growth** — `store/observability.py:148-161`. `run_log`/`llm_usage`
      grow unbounded and full per-run log text is stored; add retention/rotation for both
      (not just `log_entry`), and consider truncating stored log text.
- [ ] **Redact secrets from captured logs** — `logging_setup.py:30-224`. Full root-logger
      output is captured unredacted into run logs and shown in the dashboard. Add a scrubbing
      filter (tokens, keys, Authorization headers, email bodies) before persistence.

### Frontend
- [ ] **Error boundaries for RSC pages** — `web/app/email/runs/page.tsx:6-9` (and siblings).
      Pages throw on API failure instead of degrading; add `error.tsx` boundaries.
- [ ] **Email detail: distinguish 404 from outage** — `web/app/email/[id]/page.tsx:24-29`.
      Any backend failure renders as 404; only `notFound()` on a real 404.
- [ ] **UTC-correct timestamps** — `web/lib/view/email.ts:74-75`, `draft.ts:48`. Timestamps
      are parsed as local, not UTC → wrong relative times for non-UTC users.
- [ ] **Debounce + sequence the logs search** — `web/components/logs-explorer.tsx:135-164`.
      Fires a request per keystroke and has no out-of-order guard; debounce input and ignore
      stale responses (request id / AbortController).

## Code review follow-ups — Low / Nit (2026-06-21)

Minor robustness/quality items; verify before acting. Full context in the review doc.

- [ ] API: cap unbounded `limit` params (`routes.py:146-175, 638-660`); don't 502 on missing
      local Gmail credential (`routes.py:16-24`); `get_email` returns all drafts with a
      different shape (`routes.py:195-202`); `bulk_update_email_status` accepts unknown/empty
      ids silently (`routes.py:211-221`); don't leak raw exception text in 500s (`routes.py:283-286`).
- [ ] Sandbox: kill the docker container on host-side timeout (`sandbox.py:94-103`); verify
      `--max-budget-usd` is a real headless `claude` flag (`sandbox.py:14-24`).
- [ ] DB/obs: index `emails` filter/sort columns (`db.py:65-87`) and `llm_usage.run_id`
      (`observability.py:61-73`); `get_obs_session` doesn't commit on exit while `get_session`
      does — align the contract (`observability.py:163-168`); add the existence guard to the
      emails branch of `_migrate` (`db.py:182-206`); run `_prune_old_logs` periodically, not
      only at startup (`observability.py:102-160`).
- [ ] Gmail: References-header dedup substring check can drop a needed Message-ID
      (`client.py:104-107`); add retry/backoff on transient Gmail errors (`client.py:157-189`).
- [ ] Injection: instruction-pattern scoring counts distinct patterns, not occurrences
      (`injection.py:58-68`).
- [ ] Pipeline/classifier: force `skip` emails to urgency 0 (`classifier.py:143-149`);
      `extract_text` silently yields "" on no text blocks (`provider.py:82-98`).
- [ ] Provider: `UsageCallback` leaks start-time entries and drops usage on LLM error — add
      `on_llm_error` (`provider.py:24-79`).
- [ ] Logging: `DbLogHandler` drops records emitted during an in-progress flush
      (`logging_setup.py:128-131`).
- [ ] Reminders: dead no-op tzinfo replace in `next_fire_at` (`service.py:87`).
- [ ] Agent: `get_agent()` lazy init has no lock → concurrent first calls leak an
      `AsyncSqliteSaver` connection (`graph.py:22-35`).
- [ ] Workflows: multi-chunk notify in one Inngest step re-sends earlier chunks on retry
      (`morning_digest.py:34-38`); `top_hn.py` worst case can exceed the 120s `run_script`
      timeout (`scripts/top_hn.py:7-15`).
- [ ] Config: `.env.example` drift — reconcile `INNGEST_DEV`/`OUTREACH_ACCOUNT` and omitted
      live settings (`.env.example`); docker-compose Inngest keys default to placeholders +
      port 8288 bound to all interfaces (`docker-compose.yml:17-26`).
- [ ] Web: `runs-proxy` passes `NaN` limit when 'limit' is non-numeric
      (`web/app/api/runs-proxy/route.ts:7-11`); `getRun(id)` interpolates user id into the URL
      without encoding (`web/lib/api.ts:257-258`); dead `revalidatePath("/drafts/${id}")`
      (`web/lib/actions.ts:51,83,97`); command-palette lacks focus trap / aria-modal
      (`command-palette.tsx:53-95`); 'g' prefix key stays armed 700ms (`app-shell.tsx:38-50`);
      `email-table` keydown listener re-subscribes per cursor move (`email-table.tsx:45-72`);
      `flashSaved` timeout not cleared on unmount (`draft-composer.tsx:51-54`); memoize
      `buildChartData`/`chartConfig` (`tokens-chart.tsx:63-79`).
