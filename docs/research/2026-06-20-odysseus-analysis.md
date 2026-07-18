# Odysseus — deep analysis & what rotom can steal

> **Date:** 2026-06-20 · **Subject:** [`pewdiepie-archdaemon/odysseus`](https://github.com/pewdiepie-archdaemon/odysseus) @ `1602674` (dev)
> **Method:** Full clone, read-only. Narrative docs read directly; the ~107K-LOC backend mined by 7 focused sub-analyses (agent core, tools, memory/RAG, scheduler/events, email, security, integrations/MCP/research). No code run, no LLM calls against either app.
> **Purpose:** Understand how Odysseus is built (decisions, patterns, features) and extract anything *novel* worth deriving for rotom. File:line cites point into the Odysseus tree.

---

## TL;DR

Odysseus is a **self-hosted, multi-user AI _workspace_** (chat, agents, deep research, documents, email, notes, calendar, image-gen, local-model serving) — a ~107K-LOC FastAPI monolith with a vanilla-JS frontend, AGPL-licensed, single-process, SQLite-backed, ChromaDB-augmented. It is the *maximalist* sibling of rotom's *minimalist* personal assistant. We are **not** building on it.

Three things make it genuinely worth studying:

1. **A documented trust boundary.** `THREAT_MODEL.md` + `src/prompt_security.py` treat all external content (email, web, memory, tool output) as untrusted *data* via a single wrapper seam. rotom has a detector; it lacks the seam.
2. **RAG-as-infrastructure with graceful degradation.** Tool selection, memory recall, and document RAG all run on the same embed-or-fall-back-to-keyword ladder. The *keyword/BM25 fallback tier needs no vector DB at all* — which is exactly the part that fits rotom's "one SQLite file" constraint.
3. **An agent loop tuned by scar tissue.** Intent-without-action nudging, verbatim-call runaway detection, force-answer, model escalation with skill-writing. These are battle-tested fixes for the same Claude failure modes rotom's LangGraph agent hits.

The single highest-value derivations for rotom: **(a)** a reusable untrusted-content wrapper for the *chat agent's* email-read path; **(b)** a **SQLite+BM25 long-term memory** tier (net-new capability, zero new services); **(c)** agent-loop hardening (nudger + runaway guard). Full prioritized list in [Recommendations](#recommendations-for-rotom).

---

## 1. What Odysseus is

| Dimension | Value |
|---|---|
| **Pitch** | "Self-hosted AI workspace for chat, agents, research, documents, email, notes, calendar, and local model workflows." |
| **Scale** | 243 Python files / ~107K LOC (excl. tests), **622 test files**, 161 JS files, `static/style.css` is **36,653 lines**. |
| **Stack** | FastAPI + uvicorn, Pydantic v2, SQLAlchemy/SQLite, ChromaDB (HTTP client) + fastembed (local ONNX), `mcp`, croniter, bcrypt + pyotp (2FA), caldav, cryptography (Fernet). Frontend is hand-written vanilla JS (no framework). |
| **Deploy** | Docker compose (+ GPU AMD/NVIDIA variants), PyInstaller native builds (macOS/Windows), systemd unit. Single asyncio process. |
| **Model access** | Local (Ollama/SGLang/llama.cpp) **and** API providers (Anthropic, Gemini, Groq, xAI, OpenRouter, OpenAI, DeepSeek), plus **subscription reuse** (ChatGPT/Copilot via device-OAuth). |
| **Audience** | Trusted users on a private network. "Treat it like an admin console." Multi-user with admin/non-admin RBAC. |
| **License** | AGPL-3.0-or-later. |

**Philosophy (inferred):** maximal capability, self-hosted/offline-capable, "everything is a tool the agent can reach," degrade-don't-crash, and a *consciously* documented security boundary. The `ROADMAP.md` is unusually candid ("I don't know what I'm doing, help") and the codebase shows the cost of that velocity: a 4,032-line `tool_implementations.py`, a 2,961-line `agent_loop.py`, flat 95-file `src/`. Their own `specs/architecture-runtime-inventory.md` is a refactor-planning doc that reads as a cautionary tale.

---

## 2. Architecture & the big decisions

- **Single FastAPI monolith, route-registration pattern.** `app.py` (~1,145 lines) imports `setup_*_routes(app, ...)` from each of 54 flat `routes/*.py` files. No blueprints/routers package; registration is linear and explicit.
- **Layering is aspirational, not enforced.** `routes/ → src/ → core/` is the intended flow, but `src/` reaches *back* into `routes/` 31 times via function-body inline imports (`tool_implementations.py` → `email_routes.py`, etc.). They know — it's documented as a smell.
- **`core/database.py` is the gravity well.** 28 ORM classes, **102 importers**. Their refactor doc explicitly says: never split this first.
- **The agent loop is the center of the universe.** `src/agent_loop.py:stream_agent_loop` is where requests are classified, tools are selected, context is budgeted, the tool-call loop runs, runaway is detected, and completion is verified. Everything else feeds it.
- **RAG is plumbing, not a feature.** ChromaDB + fastembed back *tool selection*, *memory recall*, and *document RAG* — three consumers of one embedding stack (`src/embedding_lanes.py`), each with a keyword fallback.
- **In-process *and* subprocess MCP.** Simple capabilities (bash, filesystem, web) are native in-process tools; four heavier ones (email, memory, rag, image-gen) run as **stdio subprocess MCP servers** so the agent dispatches them identically to user-added third-party servers.
- **Security is a stated boundary, not vibes.** `THREAT_MODEL.md` enumerates roles × capabilities, the prompt-injection policy, the internal-tool loopback, CSP, and *known gaps* with issue links.
- **Degrade, don't crash.** Every external dependency (ChromaDB, embeddings, SearXNG, email accounts, providers) has a health probe and a fallback path. "The app still degrades to keyword fallback" is a literal comment in `requirements.txt`.

---

## 3. Subsystem deep-dives

Each section: **how it works → the decision/pattern → what's novel**. Cites are `odysseus:file:line`.

### 3.1 Agent core & decision-making (`src/agent_loop.py`)

- **Pre-classification before the loop.** Three cheap passes run *before* any tool call: `_detect_admin_intent` (`agent_loop.py:691`), `_classify_agent_request` (regex → domains like email/files/web/notes, `:763`), and RAG tool selection (`:1937`). The classification both seeds domain tools *and* appends domain-specific rule-text to the system prompt.
- **The loop** (`stream_agent_loop`, `:1832`) is a `for` over `MAX_AGENT_ROUNDS = 50`. Stop condition: a round with no tool blocks → break (`:2695`), unless a supervisor re-enters.
- **Runaway detection, two signals** (`:2708`): (1) hash each tool block as `f"{type}:{content[:120]}"` and trip if any *identical* signature appears ≥15× — **distinct** calls to the same tool (18 different calendar creates) are *not* counted, killing false-positives on legit batches; (2) a stuck-rounds streak (re-issuing a recent signature with no new text) trips at 4. On trip → **force-answer**: inject a "write the answer or declare blocked" system message and *strip all tool schemas* from the next round (`:2740`) so the model physically cannot call a tool.
- **Intent-without-action nudger** (`:2663`): a regex (`_INTENT_RE` = "let me / I'll / going to" + action verb) detects when the model *announced* an action on a no-tool round but didn't call anything, and injects a sharp demand for the actual call. Capped at 2 nudges. **This is the single most common Claude failure mode**, handled structurally.
- **Plan mode & tool policy** (`src/tool_policy.py`): `ToolPolicy` is a frozen dataclass; `build_effective_tool_policy` (`:174`) can set `block_all_tool_calls=True` when the user says "don't use tools" — schemas aren't even sent. Plan mode permits read-only tools, blocks mutators, and **fails closed** (unknown tool → treated as mutating).
- **Model escalation / "teacher"** (`src/teacher_escalation.py`): on a *regex-detected failure*, fire-and-forget (`asyncio.Task`, non-blocking) a stronger "teacher" model with the failure trace (wrapped in `<<<UNTRUSTED_TRACE>>>`), which (a) explains the fix and (b) writes a `SKILL.md` procedure injected on future turns. The teacher's own output is re-evaluated; if *it* sounds uncertain, the skill is dropped (`:404`).
- **Completion verifier** (`:1699`): an opt-in second model with fresh context independently checks whether the claimed deliverable actually exists.
- **Context management** (`src/context_compactor.py`, `src/context_budget.py`): soft-trim drops oldest turns but protects `_protected`-flagged injected context (active email/doc) and the last 10 turns; active compaction at 85% fill summarizes the older half via a structured 1024-token self-summary. Budget auto-scales to 85% of the *discovered* model context window when unset.

### 3.2 Tool system & RAG-based tool selection (`src/tool_index.py`)

- **Two parallel declarations, intentionally not DRY.** `FUNCTION_TOOL_SCHEMAS` (`tool_schemas.py:23`, ~67 OpenAI-style schemas) is sent to API models; `BUILTIN_TOOL_DESCRIPTIONS` (`tool_index.py:69`, 68 entries) is *richer embedding text* written for semantic search — it includes intent synonyms and anti-patterns ("do NOT use for X") that don't belong in a JSON `description`.
- **The novel core: per-request tool retrieval.** Instead of sending all ~68 schemas every turn, each tool's embedding description is indexed in ChromaDB; at request time the query is embedded and the **top-8** tools retrieved (`retrieve`, `:295`). This directly fights "tool schemas eat the context window."
- **A three-tier degradation ladder** (`agent_loop.py:1946`): embedding retrieve (1.5s timeout) → **keyword hints** (`_KEYWORD_HINTS`, ~25 frozenset→toolset maps, word-boundary anchored, `:344`) → `ALWAYS_AVAILABLE` (3 tools). Plus a regex layer for typo-resilient scheduling/URL intent, and a **domain-seed union** (`:1981`) so obvious requests aren't lost to a vector miss.
- **Negative steering** (`:583`): for "save contact for X" patterns, `manage_memory` is *removed* from the set even though it's always-available — prevents the model picking a syntactically-present wrong tool.
- **Security at execution** (`src/tool_security.py`): four sequential layers — per-request denylist → plan-mode policy → admin-tool check → `NON_ADMIN_BLOCKED_TOOLS` (+ all `mcp__*`). Fails closed on non-string tool names. Blocked tools are also *hidden from the prompt*, not just refused at runtime.

### 3.3 Memory & RAG (`src/memory.py`, `src/rag_vector.py`, `src/embedding_lanes.py`)

- **Memory is a JSON file + hybrid recall.** Records (`id, text, timestamp, source, category, owner, uses, metadata`) live in `memory.json` (`memory.py:107`). Recall (`chat_processor.py:69`) blends **0.55 vector + 0.40 BM25 (computed in-process per call) + 0.05 recency**, with category boosts (+20–40%) when the query mentions identity/contact/preference. **When the vector store is down it degrades to pure BM25** (0.95 + 0.05 recency) — no service required.
- **`uses` counter** increments on actual injection (`chat_processor.py:243`) → enables "most-referenced facts" and future decay/pruning.
- **`remember: X` inline command** (`memory.py:87`): a regex intercept turns a message into a memory write with zero tool-call overhead.
- **Embedding "lanes"** (`embedding_lanes.py`) solve ChromaDB's locked-dimension constraint: each collection is duplicated per embedding backend (`_fastembed`, `_custom`), fingerprinted by `sha256(model+dim)`; a model change deletes & **re-embeds in 100-doc batches** with rollback.
- **RAG pipeline** (`rag_vector.py`): sentence-aware chunking (1000 chars / 200 overlap), over-fetch `k*6` then re-score 70/30 vector/keyword, dedup, fall back to linear keyword scan on any error. Retrieved content is injected as an `untrusted_context_message`.
- **The portability lesson for rotom:** the *entire* memory feature works with **no vector DB** — JSON storage + in-process BM25 — and silently upgrades to vector when fastembed is present. Storage layer never changes; only ranking improves.

### 3.4 Scheduler, events, reminders, observability (`src/task_scheduler.py`, `src/event_bus.py`)

- **Scheduled *agent* tasks** (not just cron jobs): a hand-rolled `TaskScheduler` (`:292`) with `asyncio.Semaphore(1)`. Tasks are **structured** (no NL parsing) — `trigger_type` (schedule/event/webhook), `schedule` (once/daily/weekly/monthly/cron), `cron_expression`; `compute_next_run` (`:97`) uses croniter / per-cadence arithmetic in the task's IANA timezone. Three task *types*: `llm` (full `stream_agent_loop`), `research`, `action` (no LLM).
- **Output routing**: `output_target` ∈ {session, notification, email, raw address} (`:898` chaining via `then_task_id` with cycle detection). One-shots auto-complete.
- **Lifecycle & observability**: `TaskRun` rows go `queued → running → success/error/aborted/skipped`. The `queued` row is created *before* the semaphore wait so the UI shows queue position. **Startup zombie sweep**: leftover `running/queued` → `aborted` ("Server restarted…"), *not* `error` (keeps crash artifacts out of error-rate metrics). `TaskDeferred`/`TaskNoop` exceptions let an action postpone or record a *skipped* run instead of a fake success. Round-exhaustion **grace summarization** prevents silent empty results (`:1739`).
- **Live-tail without polling** (`src/agent_runs.py`): an in-memory SSE relay — each run keeps a buffer + subscriber queues; new connections **replay the buffer** then stream live, retained 180s after last disconnect. Survives tab-close/navigation without WebSockets (but not process restart).
- **Event bus** (`event_bus.py`, 120 lines): `fire_event(name, owner)` finds `trigger_type="event"` tasks, increments a counter, fires at threshold (e.g. memory consolidation after 5 `memory_added` events). Decouples housekeeping from wall-clock.
- **Reminder personas** (`src/reminder_personas.py`): five named voices (Socrates, Razor, Nietzsche, Spark, Odysseus); the synthesis prompt prepends the persona and "keep it under 18 words, in the voice above." Proactive voice-styling for nudges.
- **Timezone** (`src/user_time.py`): per-request UTC offset + IANA name in `contextvars`; scheduled tasks resolve tz from the task row (no request context).

### 3.5 Email subsystem (`routes/email_*.py`, `src/email_thread_parser.py`)

- **Per-email LLM calls (not batched).** Each new email gets up to three independent calls: urgency (`critical|high|medium|low|none` + reason, time-anchored; `email_pollers.py:703`), tag+spam (14-tag fixed set; `:831`), and summary (1–3 bullets between `<<<SUMMARY>>>` markers; `:402`). rotom's *single batched* call is tighter and cheaper.
- **Push by reuse**: critical/high emails trigger an **HTML alert email sent back to the user's own inbox** (`:763`) — zero extra infra, lands in the UI they already watch.
- **Calendar auto-extraction** (`:491`): an LLM decides create/update/cancel against existing events; then a **regex enrichment layer** adds Zoom/Meet/Teams links, FedEx/UPS/DHL/Amazon tracking, flight numbers, PNR, gate/seat, confirmation codes — *no LLM*. (LLM extracts intent; regex fills deterministic fields.)
- **Reply drafts with deep context** (`email_helpers.py:1344`): the manual path injects `_pre_retrieve_context` (named-entity search across past mail, capped at 3 terms to bound exfil) and `_fetch_sender_thread_context` (last 3 emails from that sender across all folders + attachment text as "REFERENCED MATERIAL"). A **learned `email_writing_style`** (extracted from sent mail) outranks generic tone rules. Output fenced in `<<<REPLY>>>…<<<END>>>`.
- **Two-status HITL gate**: AI agent drafts land as `agent_draft`; an approve endpoint flips to `pending` (which the scheduled sender then delivers).
- **Polling**: interval-based (`while True: sleep(1800)`), *not* IMAP IDLE; multi-account fan-out with per-account error isolation (`:167`); `_max_process = 5` per pass caps LLM cost on a backlog; dedup via 5 message-id cache sets; synthetic SHA-256 id when `Message-ID` is missing.
- **Thread/quote parsing** (`email_thread_parser.py`): BeautifulSoup detection of Gmail/Apple/Outlook/Yahoo/Thunderbird quote containers; plaintext `>`-level + "On … wrote:" attribution in 20+ locales + CJK; versioned cache (`THREAD_PARSER_VERSION = 6`). Splits new content from quoted history. (No signature stripping.)
- **Email-as-MCP** (`mcp_servers/email_server.py`): 14 tools (list/read/draft/reply/archive/bulk/search…), descriptions steer toward *draft* over *send*; owner scoped via a hidden `_odysseus_owner` arg in a `ContextVar`.

### 3.6 Security & infra resilience (`src/prompt_security.py`, `core/middleware.py`)

- **The untrusted-content wrapper** — the pattern rotom should adopt for its agent read-path:
  ```python
  # odysseus:src/prompt_security.py
  def untrusted_context_message(label, content):
      text = _escape_guard_markers(str(content))   # neutralize injected <<<…>>> delimiters
      return {"role": "user",                        # user role — cannot override system
              "content": f"{UNTRUSTED_CONTEXT_HEADER}\n{GUARD_OPEN}\nSource: {_sanitize_label(label)}\n{text}\n{GUARD_CLOSE}",
              "metadata": {"trusted": False, "source": label}}
  ```
  `UNTRUSTED_CONTEXT_POLICY` is a one-time system preamble; the per-message header names the threat; `_escape_guard_markers` stops delimiter-breakout; label CR/LF stripped. **Surfaces that must go through it:** emails, fetched pages, retrieved docs, memories, skills, any externally-sourced tool output.
- **Internal-tool loopback** (`core/middleware.py`): in-process agent tools call admin-gated HTTP routes with `X-Odysseus-Internal-Token` (random `secrets.token_hex(32)` per process, never persisted), checked with `compare_digest`; the `internal-tool` username is reserved so no real account can impersonate it. *(rotom doesn't need this — its tools are in-process Python, not HTTP.)*
- **SSRF**: `url_security.py` (strict — blocks RFC-1918/loopback/link-local/metadata, resolves every A/AAAA, fails closed) for untrusted URLs; `url_safety.py` (permissive — allows local Ollama, blocks only metadata/link-local by default) for admin endpoints; `webhook_manager.py` **re-validates at delivery time** (DNS-rebinding defense) and `follow_redirects=False`.
- **Secret vault** (`secret_storage.py`): Fernet (AES-128-CBC+HMAC), key at `data/.app_key` chmod 0600, values prefixed `enc:` for idempotency, wrong-key → `""` not 500. Threat model: protects a stolen DB/backup, not process compromise.
- **Degraded-state probes** (`service_health.py`): 5 subsystems × {ok, degraded, down, disabled}; bounded at every level (per-probe 4s, fan-out 8s, subsystem 10s, aggregate 14s); URLs scrubbed via `_safe_url`, errors mapped to category tokens (never `str(exc)`).
- **Atomic IO** (`core/atomic_io.py`): write tmp (`.tmp.{pid}`) → `fsync` → `os.replace`. **Error sanitizer** redacts IPs/URLs before logs hit disk.

### 3.7 Integrations, MCP, deep research

- **Coding agents — the inversion.** Odysseus does **not** run Claude Code/Codex; it publishes a downloadable **skill bundle** (`/api/claude/plugin.zip`) containing a `SKILL.md` + a stdlib `odysseus_api.py` helper. The user installs it into *their own* Claude Code/Codex session, which then calls back into Odysseus over **scope-checked API tokens**. A `/api/codex/capabilities` manifest tells the agent what it's allowed to do; the SKILL.md enumerates a "Forbidden Bypass Pattern" (no SSH, no direct SQLite, no MCP-helper calls). **Odysseus is the server; the agent is the client.** This is the opposite of rotom's container-owns-execution model.
- **Subscription reuse**: ChatGPT (`chatgpt_subscription.py`) and Copilot (`copilot.py`) piggyback on the user's existing subscription via device-OAuth (reusing VS Code's / Codex's public client IDs), no API keys.
- **MCP client** (`mcp_manager.py`): stdio/SSE/HTTP transports; third-party tool schemas **sanitized** before prompt splicing (control chars stripped, field-name/param caps); read-only classification via MCP annotations → verb heuristic → **fail closed**; OAuth tokens persisted encrypted (`mcp_oauth.py`, PKCE + dynamic client reg).
- **Deep Research** (`deep_research.py`): IterResearch loop — Plan → (Think→Search→Extract→Synthesize→Decide)×N → Final; time-bounded (300s), `min_rounds`/`max_empty_rounds` guards, **date-grounding** to avoid training-cutoff years, affirmation-phrase detection so "ok" isn't treated as the query. Reports rendered to HTML and **sanitized with `nh3`** (untrusted LLM/crawled content).

---

## 4. rotom vs Odysseus — philosophy & overlap

| Axis | rotom | Odysseus |
|---|---|---|
| **Scope** | Personal assistant, messaging-first | Multi-feature workspace |
| **Users** | Single user | Multi-user + RBAC |
| **Interface** | Telegram + Next.js dashboard | Web app (vanilla JS) |
| **Models** | Anthropic only | Local + 7 API providers + subscriptions |
| **Agent** | LangGraph + SqliteSaver | Hand-rolled `stream_agent_loop` |
| **State** | One SQLite file | SQLite + ChromaDB + JSON files |
| **Email** | Gmail API, batched triage, auto-draft, HITL | IMAP/SMTP, per-email triage, calendar extraction, learned style |
| **Memory** | **None** | JSON + BM25 + vector |
| **Coding agent** | Owns a container (issue→PR→CI-fix) | Exposes scoped API; user's own CLI is the client |
| **Injection defense** | Detect-and-quarantine at triage | Wrap-as-data seam everywhere |
| **Ethos** | Minimal, portable, HITL gates | Maximal, self-hosted, "admin console" |

**The relationship:** Odysseus has *already built and debugged* the features rotom is growing toward (memory, scheduled agent tasks, deep email context, a hardened agent loop). It's a parts bin, not a blueprint. The discipline is to take the *patterns* and leave the *weight* — Odysseus's own runtime-inventory doc is proof of what unmanaged scope costs.

---

## Recommendations for rotom

Calibrated against what rotom **already has**: a triage-time injection *detector* (`gmail/injection.py`), `record_run` observability + a polling logs explorer, APScheduler + reminders (`tools/reminders/`), a notify-channel layer in design, a containerized coding agent, and 13 agent tools. Effort: **S** ≈ hours, **M** ≈ a day or two, **L** ≈ a small project.

### Tier 1 — high value, fits the minimalism, do soon

| # | Idea | Why for rotom | Effort |
|---|---|---|---|
| 1 | **Untrusted-content wrapper seam** (`untrusted_context_message` + one-time `UNTRUSTED_CONTEXT_POLICY` system preamble) applied to the **chat agent's** email-read tools (`get_email`/`list_emails`/`create_draft_for_email`) and any future fetch/MCP output. | rotom's detector covers the *triage* path; the *agent* still feeds stored bodies to Claude untagged. This closes the defense-in-depth gap (esp. with a coding-agent trigger reachable from chat). Small, self-contained, copy the escaping logic. **Not a duplicate of `injection.py`.** | S |
| 2 | **SQLite + BM25 long-term memory** — a `memories` table in the existing DB, in-process BM25 recall on each turn (top-k above threshold), `remember: X` inline command, `uses` counter, category boosts. Optional fastembed upgrade later (storage unchanged). | rotom has **no memory** — this is the biggest *new capability* on offer, and Odysseus proves it works with **zero new services**. Perfectly fits "one SQLite file, portable." | M |
| 3 | **Agent-loop hardening for LangGraph**: intent-without-action nudger (regex "I'll/let me" + no tool call → re-prompt), identical-call runaway guard (hash `tool+args[:120]`, trip on verbatim repeats — *not* per-tool totals), force-answer fallback. | Directly fixes the most common Claude failure modes; cheap to bolt onto the graph; the args-hash approach avoids false-positives on legit batches. | S–M |
| 4 | **Email thread/quote stripping** before classify/draft — port the multi-client quote detection from `email_thread_parser.py`. | Cleaner LLM input = cheaper + better classification *and* replies that don't re-quote history. Pure function, easy to test. | M |
| 5 | **Observability refinements**: `skipped`/`TaskNoop` runs, `aborted ≠ error` on restart, `queued` state, and a per-triage-pass cap (`_max_process`). | Refines the *just-shipped* `record_run` seam; keeps crash/no-op artifacts out of error-rate metrics; caps cost when a mail backlog drains after downtime. | S |

### Tier 2 — worth planning

| # | Idea | Why for rotom | Effort |
|---|---|---|---|
| 6 | **Scheduled *agent* tasks** — let the user schedule the agent itself ("every morning, summarize unread and message me"), with `output_target` routing into the **notify-channel layer** being designed. One-shot/recurring, grace-summary on round exhaustion, optional chaining. | Natural next step on top of APScheduler + reminders + notify; turns rotom from reactive to proactive. `output_target` and the notify layer are made for each other. | M–L |
| 7 | **Reply-draft context enrichment** — sender-thread context + learned writing-style + `<<<REPLY>>>` output fencing. | Deepens rotom's existing auto-draft quality toward "sounds like me, knows the thread." | M |
| 8 | **SSE replay-buffer live-tail** for the runs/logs explorer (replace polling). | Direct upgrade to current polling; live-tail that survives navigation without WebSockets. | M |
| 9 | **Event-bus counter triggers** for housekeeping (e.g. consolidate memory after N writes). | Lightweight decoupling; pairs with #2 and #6. | S–M |
| 10 | **Reminder personas** — voice-styled proactive nudges. | Tiny, and rotom already has a SOUL/persona page in the dashboard — this gives it teeth. | S |

### Tier 3 — defense-in-depth / when-needed

- **Tool selection** (keyword-hints + domain-seed map; *no vector DB*) — only once rotom passes ~20–25 tools. At 13 it's premature; sending all schemas is fine.
- **Context compaction** for long Telegram threads (`_protected` flag for injected email/draft context) — or just enable Anthropic **server-side compaction** (beta) instead of hand-rolling.
- **SSRF guard + fire-time URL re-validation** if rotom adds a fetch tool or for the coding-agent trigger; `sanitize_error` to scrub IPs/URLs from logs/Telegram.
- **Fernet `enc:` secret storage** *only if* a secret moves from `.env` into SQLite (e.g. OAuth tokens).
- **Atomic JSON writes** for any JSON state file rotom writes.
- **Degraded-state `/health` probe** (bounded timeouts; ok/degraded/down/disabled) over Gmail, Anthropic, ntfy — rotom already does degraded *reporting*; this is the probe shape behind it.
- **Model escalation** (Haiku→Opus on detected failure, optionally with skill-writing) and a **completion-verifier** for the coding-agent flow — more speculative, higher cost.

### Anti-recommendations — deliberately skip

These are Odysseus being a *product*; copying them would betray rotom's reason to exist.

- **Multi-user RBAC, internal-tool loopback token, reserved usernames** — rotom is single-user with in-process Python tools; there's no HTTP loopback to secure.
- **ChromaDB as a hard dependency** — use SQLite/BM25; keep fastembed strictly optional. Portability is the point.
- **Local model serving (Cookbook), image gen, document editor, deep-research-as-a-feature** — out of scope; Anthropic-only is a deliberate choice.
- **Exposing rotom-as-MCP** — the agent *is* rotom; wrapping itself in MCP adds ceremony with no gain. (Consuming an external MCP server later — e.g. Linear — is the useful direction.)
- **Subscription reuse (ChatGPT/Copilot device-OAuth)** — irrelevant; rotom uses the Anthropic API.
- **4,000-line files / flat `src/`** — keep rotom's clean module boundaries (`tools/gmail/*`, `observability/*`, …). Odysseus's own refactor doc is the warning.

### One architectural fork worth pondering

rotom **owns** its coding agent (GitHub issue → container → CI-fix → draft PR). Odysseus **inverts** it: a scoped-token API + downloadable `SKILL.md` that the user's *own* Claude Code session calls back into. They're not mutually exclusive — rotom could keep the containerized path for autonomous/headless runs **and** offer a "bring-your-own Claude Code" mode (scoped `/api/agent/` + a skill bundle) for zero-container local work, with a capability manifest gating what the session may touch. That's the one genuinely *novel-to-rotom* idea in the integrations space.

---

## Appendix — key Odysseus files

`app.py` · `src/agent_loop.py` · `src/tool_index.py` · `src/tool_schemas.py` · `src/tool_security.py` · `src/tool_policy.py` · `src/teacher_escalation.py` · `src/context_compactor.py` · `src/context_budget.py` · `src/memory.py` · `src/rag_vector.py` · `src/embedding_lanes.py` · `src/chat_processor.py` · `src/task_scheduler.py` · `src/event_bus.py` · `src/agent_runs.py` · `src/reminder_personas.py` · `src/user_time.py` · `routes/email_pollers.py` · `routes/email_helpers.py` · `src/email_thread_parser.py` · `mcp_servers/email_server.py` · `src/prompt_security.py` · `src/url_security.py` · `src/url_safety.py` · `src/secret_storage.py` · `src/service_health.py` · `core/middleware.py` · `core/atomic_io.py` · `src/mcp_manager.py` · `src/deep_research.py` · `THREAT_MODEL.md` · `specs/architecture-runtime-inventory.md`
