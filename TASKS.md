# rotom — Pending Tasks & TODOs

Working tracker for open work. The long-form roadmap lives in [`TODO.md`](./TODO.md);
this file is the short list of what's actively pending + the current bug queue.

Last updated: 2026-06-13

---

## 🐞 Observability bug fixes — ✅ FIXED (2026-06-13)

Root cause for the date bugs (#2, #3, #4): the brittle `endsWith("Z") ? ts : ts+"Z"`
pattern. The backend emits three timestamp shapes — naive (`...024446`), explicit
offset (`...+00:00`), and date-only (`2026-06-11`). Appending `Z` to an offset value
(`...+00:00Z`) → **Invalid Date**; to a date-only → bogus midnight-UTC time. Fixed by a
single `normalizeTs()` helper in `web/lib/obs-utils.ts` used everywhere.

- [x] **1. Logs explorer — run context buried.** Added a `kind` badge (+ `#run_id`) to each
      log row so the run ("gmail_triage", etc.) is directly visible; timestamps now render
      via the fixed `formatTs`. (`logs-panel.tsx`, `logs-explorer.tsx`)
- [x] **2. Run detail — start time not visible.** Promoted "Started" into the stats header;
      dropped the buried bottom line. (`run-detail-live.tsx`)
- [x] **3. Execution logs "Invalid Date".** `formatTs` now uses `normalizeTs` (handles the
      `+00:00` offset) + an `isNaN(getTime())` guard. (`obs-utils.ts`, `logs-panel.tsx`)
- [x] **4. Usage "Time" always 5:30 AM.** Column is now "Date", rendered date-only via the
      new `formatDate`. (`observability/page.tsx`, `obs-utils.ts`)
- [ ] **5. Usage "Avg latency" always —.** NOT a code bug: `provider.py` computes latency and
      `record_usage` persists it. The `—` is **stale/un-migrated data** — old rows predate the
      `latency_ms` column. Populates once the app restarts (runs the column migration) and new
      LLM calls land. *(verify after next deploy; no code change)*
- [x] **6. Usage rows too wide.** Tightened padding (`px-4 py-2`), `max-w-4xl`, compact text.
      (`observability/page.tsx`)
- [x] **7. Recent Runs redundant `success` pill.** Removed the raw status pill; the colored
      spine bar + description already convey status. (`runs-list.tsx`)

---

## ⏳ Landing page (rotom-flex) — loose ends
- [ ] **Custom domain DNS** — add Cloudflare record so `rotom.example.com`
      resolves: `CNAME` name `rotom` → `cname.vercel-dns.com`, **DNS only (grey cloud)**.
      SSL auto-issues after. *(user action)*
- [ ] **`site/.gitignore`** (Vercel-created, untracked) — decide: commit or leave.

---

## 📋 Near-term features (not started)
- [x] **Email "Sent with rotom" footer** — implemented (2026-06-13). Multipart/alternative
      HTML footer with a clickable anchor; per-draft switch (default from global config),
      applied at send + save-to-gmail. 📄 Spec: `docs/superpowers/specs/2026-06-13-email-footer-design.md`
- [x] **Unify run sources** — v1 implemented (2026-06-13).
      📄 Spec: `docs/superpowers/specs/2026-06-10-unify-run-sources-design.md`
  - [x] Schema deltas (`source`, `external_id`, `external_url`, `parent_run_id`,
        `last_heartbeat_at`) + `RunStatus.INTERRUPTED` + migrations-lite.
  - [x] `RunStart` payload; `record_run(kind, source=…, external_id=…, external_url=…)` with
        **automatic parent/child nesting** (captures enclosing run id).
  - [x] Per-source wiring: triage scheduler/manual, draft `manual`, `reminder_fire`.
  - [x] **Fail-safe instrumentation** — `get_sink()` always wraps in `CompositeSink`;
        `record_run` is fully defensive (sink down → `run_id=None`, body still runs, stdout
        warning).
  - [x] **Interrupted-run handling** — heartbeat (60s daemon) + 5-min reaper job + startup
        sweep; flips zombie `running` rows to `interrupted` (excludes Inngest).
  - [x] Query/API/UI — `source`+`kind` facets, source badges, parent breadcrumb, sub-runs
        list, "View in Inngest →" link, `interrupted` status styling.
  - [x] **Read-path resilience** — `/api/observability/*` routes degrade to empty/null (not
        500) via `_safe_obs_read` when the DB is unavailable; dashboard stays usable.
- [ ] **First-class Inngest run tracking (v2)** — middleware-driven idempotent rows + status
      sync. v1 is link-only (columns + "View in Inngest" link landed; no rows created).
      📄 Spec: `docs/superpowers/specs/2026-06-10-unify-run-sources-design.md` (§ Out of scope v2+)
  - [ ] **`record_run` for async/replayed Inngest workflows.** `record_run` is a sync
        contextmanager (ContextVar + heartbeat thread) and cannot wrap an Inngest workflow
        body — the engine replays the function each step, so it'd dupe rows/threads. Resolve
        the unified top-level `RunLog` row for durable workflows via `start_run`/`finish_run`
        in dedicated idempotent steps keyed on the Inngest run id; also add an explicit
        `parent_run_id=` arg so per-step runs can nest. Blocks the coding-agent's top-level
        run tracking. 📄 `docs/superpowers/specs/2026-06-08-coding-agent-design.md` (§ Observability)
- [ ] **Chat-turn tracing (v2)** — make Telegram/draft-chat turns first-class so chat-triggered
      work links back to the originating turn.
- [ ] **Tool-call counts** — per-run agent tool-call metrics (needs agent-side hook).
      📄 Spec: `docs/superpowers/specs/2026-06-09-observability-design.md` (referenced; not yet specced in detail)

---

## 📚 Broader roadmap
See [`TODO.md`](./TODO.md) for the full backlog: smart quota fallback, sent-draft
archive view, email retention/cleanup, GitHub/Linear/Calendar/Twitter tools,
long-term memory, ntfy push channel, guardrails (prompt + action), security hardening,
and infra/ops (always-on deploy, Postgres migration, observability DB backup).

Roadmap items with an existing spec:
- **Coding agent (GitHub F2)** — issue URL → containerized Claude coder → draft PR →
  bounded CI-fix loop → reviewer+security findings comment. **Code complete (2026-06-14),
  pending first live run.** Tasks 1–9 implemented + reviewed (207 tests green); Task 10 is
  manual: `docker build -f Dockerfile.coding -t rotom-coding:latest .`, set
  `CLAUDE_CODE_OAUTH_TOKEN` / `CODING_AGENT_REPOS`, `gh` push auth, then a real run on a
  throwaway issue. 📄 Spec `docs/superpowers/specs/2026-06-08-coding-agent-design.md` ·
  Plan `docs/superpowers/plans/2026-06-14-coding-agent.md` · Docs `docs/coding-agent/`

Shipped features, specs kept for reference:
`docs/superpowers/specs/2026-06-07-workflows-inngest-design.md` (workflows/Inngest),
`docs/superpowers/specs/2026-06-08-draft-composer-design.md` (draft composer),
`docs/superpowers/specs/2026-06-08-injection-detection-design.md` (injection detection),
`docs/superpowers/specs/2026-06-09-observability-design.md` (observability).
