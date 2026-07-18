<p align="center">
  <img src="assets/rotom-logo.svg" alt="rotom" width="128" height="128" />
</p>

<h1 align="center">rotom</h1>

<p align="center">
  Personal AI assistant — a Telegram chat agent with multi-account Gmail triage
  and a dashboard for reviewing AI-drafted replies.
</p>

<p align="center">
  <a href="https://github.com/DSdatsme/rotom/actions/workflows/ci.yml"><img src="https://github.com/DSdatsme/rotom/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="https://github.com/DSdatsme/rotom/actions/workflows/codeql.yml"><img src="https://github.com/DSdatsme/rotom/actions/workflows/codeql.yml/badge.svg" alt="CodeQL" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT" /></a>
  <img src="https://img.shields.io/badge/python-3.12-blue.svg" alt="Python 3.12" />
  <img src="https://img.shields.io/badge/Next.js-16-black.svg" alt="Next.js 16" />
</p>

```
Telegram ──▶ Chat agent (LangGraph) ──▶ Triage pipeline ──▶ SQLite
                                            ▲                  │
                  APScheduler (cron) ───────┘                  ▼
              Next.js dashboard ◀── FastAPI ◀── drafts (review → Send)
```

- The agent **never sends email**. It classifies, summarizes, and drafts.
  Sending happens only when you press **Send** on the dashboard.
- Email content is treated as untrusted input (prompt-injection hardening).
- LLM provider is swappable (`MODEL_PROVIDER`); Anthropic is wired up.
- All state lives in `./data` (SQLite) — portable between laptop and VPS.

## Setup

### 1. Prerequisites

- A Telegram bot token from [@BotFather](https://t.me/BotFather), and your chat id
  (message [@userinfobot](https://t.me/userinfobot)).
- A GCP OAuth client (Desktop app type) with the Gmail API enabled —
  gives you `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET`.
- An Anthropic API key.

### 2. Configure

```bash
cp .env.example .env   # fill in tokens/keys
```

You can customize the following optional features in your `.env`:
- **`SOUL_FILE`**: Path to a markdown file (e.g. `./data/SOUL.md`) where you can define your persona, tone, and writing samples. Edit this directly in the `/soul` dashboard!
- **`ATTACHMENTS`**: Comma-separated list of attachments (e.g. `resume:./data/resume.pdf`) that the agent can attach to outgoing drafts.
- **`OUTREACH_ACCOUNT`**: Specify the default Gmail account name to send cold outreach drafts from.

### 3. Authorize Gmail accounts (one-time, opens a browser)

```bash
cd api && uv sync
uv run python -m app.tools.gmail.auth_setup personal
# repeat per account; paste the printed GMAIL_<NAME>_REFRESH_TOKEN into .env
# and list the names in GMAIL_ACCOUNTS=personal,work,...
```

### 4. Run

**Docker (recommended):**

```bash
docker compose up -d --build
```

**Native (dev):**

```bash
make dev      # API + Inngest + dashboard together (Ctrl-C stops all)
make api      # API only  (api + bot + scheduler on :8000)
make web      # dashboard only (:3000)
make help     # list targets
```

Dashboard: http://localhost:3000 · API: http://localhost:8000/api/health

## Usage

- Message your bot: “check my emails” → triage digest in chat.
- Ask follow-ups: “what did the bank say?”, “draft a reply to #3”.
- Scheduled triage runs on `GMAIL_TRIAGE_CRON` (default every 6h) and pings you
  only when something is worth seeing.
- Review drafts at `/email/drafts` → edit → **Save** / **Send** / **Discard**.
- **Cold Outreach**: Create new, context-aware outreach drafts from scratch using the "Create New Draft" button.
- **SOUL Persona**: Continuously refine your AI writing persona in the dashboard under `/soul`.
- **Observability**: `/email/runs` shows background runs (status, duration, tokens, latency,
  logs); `/observability` charts LLM token usage over time and `/observability/logs` is a
  searchable, live-tailing log explorer. See [`docs/observability/`](./docs/observability/).

## Development

```bash
cd api && uv run pytest        # unit tests (Gmail/LLM faked)
cd web && npm run build        # type-checked production build
```

## Roadmap (from the full blueprint)

Reminders & NL scheduling · approve-to-send from Telegram · WhatsApp gateway ·
Linear · GitHub/coding agents · long-term memory.
