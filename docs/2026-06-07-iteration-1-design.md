# rotom — Personal AI Assistant, Iteration 1: Core Agent + Gmail Triage

## Context

`a.txt` is a blueprint for a unified personal AI ecosystem: a messaging-first agent (LUI) that handles email, reminders, Linear, and coding agents with HITL gates. The full vision is too large for one build, so iteration 1 (decided with user) is:

- **Telegram** as the command interface (not WhatsApp — official API, zero friction; gateway abstracted so WhatsApp can slot in later)
- **LangGraph tool-calling chat agent** with persistent checkpointing
- **Gmail triage rebuilt natively** (user's existing [gmail-summarizer](https://github.com/youruser/gmail-summarizer) is a pattern reference only — multi-account refresh tokens, KEY_SENDERS/EXCLUDED_TOPICS — not a dependency)
- **Drafts stored in local DB**, reviewed/edited/sent from a **Next.js dashboard** (the Send button IS the human-in-the-loop gate; agent never sends autonomously)
- **Dashboard is the long-term UI home for all integrations** (Email now; GitHub, Linear, Reminders later) with an extensible sidebar nav — adding a future integration means adding a route + one nav entry, no shell rework
- **Anthropic** LLM behind a swappable provider factory
- **Portable**: docker-compose, all state in one SQLite volume; runs on laptop now, VPS later

Reviewed [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus) at user request — decision: don't build on it, but borrow (1) injection-hardened prompts (email content = untrusted input), (2) degraded-state reporting in digests, (3) its triage UX (urgency levels, auto-tagging) as category reference.

## Architecture

```
Telegram ──long-poll──▶ Chat Agent (LangGraph, tool-calling, SqliteSaver)
                            │ tools: run_triage, list_emails, get_email,
                            │        draft_reply, list_drafts
                            ▼
                    Triage Pipeline (deterministic fn)
                    fetch ▶ dedup ▶ classify ▶ store ▶ digest ▶ auto-draft
                            ▲                            │
APScheduler ────────────────┘ (cron, SQLAlchemyJobStore) └──▶ Telegram digest

FastAPI (JSON API, bearer token) ◀── Next.js dashboard (drafts: view/edit/save/send/discard)
       └──▶ Gmail API send (only via UI Send button)

SQLite (single volume file): emails, drafts, processed-IDs, checkpoints, jobs
```

Two containers via docker-compose: `api` (Python 3.12, one asyncio process running FastAPI + Telegram bot + APScheduler) and `web` (Next.js App Router).

## Repo layout

```
api/
  pyproject.toml            # uv-managed
  app/
    main.py                 # asyncio entrypoint: FastAPI (uvicorn) + telegram bot + scheduler
    config.py               # pydantic-settings; all env vars
    llm/provider.py         # get_chat_model(role) -> BaseChatModel; MODEL_PROVIDER env (anthropic default)
    agent/graph.py          # LangGraph tool-calling agent, SqliteSaver, thread_id = telegram chat_id
    agent/tools.py          # run_triage, list_emails, get_email, draft_reply, list_drafts
    agent/prompts.py        # system prompt; email content wrapped as untrusted data
    gmail/client.py         # multi-account: fetch unread, get full message, create/send reply (threaded)
    gmail/auth_setup.py     # CLI: one-time OAuth flow per account, prints refresh token
    triage/pipeline.py      # deterministic: fetch → dedup → classify → store → digest → auto-draft
    triage/classifier.py    # single batched LLM call, structured output; KEY_SENDERS/EXCLUDED_TOPICS rules
    telegram_bot/bot.py     # python-telegram-bot long-poll; owner chat-id guard; digest sender
    scheduler/jobs.py       # APScheduler + SQLAlchemyJobStore; triage cron from env
    store/db.py             # SQLAlchemy models: Email, Draft, ProcessedMessage; session helpers
    api/routes.py           # /api/drafts CRUD, /api/drafts/{id}/send, /api/emails; bearer-token auth
  tests/                    # pytest: classifier parsing, dedup, digest format, draft MIME, API routes
web/
  (Next.js App Router + Tailwind + shadcn/ui)
  app/layout.tsx            # dashboard shell: persistent sidebar nav (shadcn sidebar) —
                            #   sections registered in one nav config; future integrations
                            #   (GitHub, Linear, Reminders, …) = add a route + one nav entry
  components/nav.tsx        # sidebar: Email (active now); future sections appear here
  app/page.tsx              # home: overview cards per integration (Email only for now)
  app/email/page.tsx        # triaged emails list (account, category, urgency, reason)
  app/email/drafts/page.tsx # pending drafts list
  app/email/drafts/[id]/page.tsx  # original email + editable draft, Save/Send/Discard
  lib/api.ts                # server-side fetch to api with API_TOKEN (token never reaches browser)
docker-compose.yml          # api + web, sqlite volume
.env.example
README.md
```

## Key decisions & details

- **Gmail scopes**: `gmail.readonly` + `gmail.send`. Sends are real replies (correct `threadId`, `In-Reply-To`/`References` headers).
- **Dedup**: `processed_messages(account, message_id)` table — no lookback-window repeats/gaps.
- **Classification** (single batched LLM call, structured output): `critical | needs_reply | fyi | skip` + one-line reason + urgency. `KEY_SENDERS` always critical; `EXCLUDED_TOPICS` always skip. Email bodies injected into the prompt inside explicit "untrusted content" delimiters with an instruction that content cannot issue instructions.
- **Auto-draft**: pipeline drafts replies for `needs_reply` emails (drafting-role model), stores as Draft(status=pending). Digest line: "📝 draft ready → dashboard link".
- **Degraded-state reporting**: per-account fetch errors collected, surfaced in digest ("⚠ work: fetch failed"), never silently dropped; pipeline continues with remaining accounts.
- **LLM provider factory**: `get_chat_model(role: "classify" | "draft" | "chat")` — per-role model config from env; only `langchain-anthropic` wired in iteration 1, interface keeps OpenAI/Gemini drop-in.
- **Telegram security**: handler drops any update where chat_id != `TELEGRAM_CHAT_ID`.
- **API auth**: static bearer token (`API_TOKEN` env) checked by FastAPI dependency; Next.js calls API only from server components/route handlers with the token.
- **Checkpointing**: LangGraph `SqliteSaver` (async) on the same SQLite file; conversation context survives restarts.

## Implementation order

1. **Scaffold** — `api/` (uv, pyproject, config.py, store/db.py with models + migrations-lite create_all), `.env.example`, docker-compose skeleton.
2. **Gmail layer** — `gmail/auth_setup.py` (port pattern from user's existing repo), `gmail/client.py` fetch + send. Verify with a real account fetch.
3. **Triage pipeline** — classifier with structured output + rules, dedup, digest formatter, auto-draft. Unit tests with mocked Gmail/LLM.
4. **Telegram bot + scheduler** — long-poll bot with owner guard, digest delivery, APScheduler cron job calling pipeline.
5. **Agent** — LangGraph graph + tools + prompts, wired into Telegram messages with chat_id thread keying.
6. **FastAPI routes** — drafts/emails endpoints, send flow, bearer auth.
7. **Next.js dashboard** — sidebar shell + nav config, home overview, Email section (emails list, drafts list, draft detail/edit with Save/Send/Discard against API).
8. **Compose + README** — end-to-end docker-compose, setup docs (GCP OAuth app, BotFather, env).

## Verification

- `pytest` in `api/` — classifier parsing, dedup, digest, MIME, route auth.
- Manual E2E: `docker compose up` → run `auth_setup.py` for one real account → message bot "check my emails" → digest arrives in Telegram → open `localhost:3000`, edit a pending draft → Send → confirm reply lands threaded in Gmail Sent.
- Scheduled path: set cron to */5 min, confirm digest fires without interaction and dedup prevents repeats.

## Out of scope (future iterations)

Reminders/NL scheduling, HITL approve-to-send via Telegram buttons, WhatsApp gateway, Linear, GitHub/coding agents, Mem0 memory, Twitter.
