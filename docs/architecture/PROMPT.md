# Generation prompt — core architecture

> Paste everything below into an AI coding agent to scaffold an equivalent system.
> This is the *skeleton* prompt; the two execution engines that sit on top (a LangGraph
> chat agent and Inngest workflows) have their own prompts in `docs/telegram-agent/`
> and `docs/workflows/`. They are deliberately separate engines sharing only the LLM
> provider factory below — don't try to unify them.

---

Build the skeleton of a personal AI assistant called by a single command. Requirements:

**Process model.** One Python 3.12 asyncio process running, concurrently:
1. A FastAPI JSON API on :8000, every route guarded by a static bearer token from env
   (`Authorization: Bearer <API_TOKEN>` checked by a FastAPI dependency).
2. A Telegram bot using python-telegram-bot long polling. Drop every update whose
   chat id != `TELEGRAM_CHAT_ID` (single-owner system). Outgoing messages must be
   chunked on newline boundaries at ~4000 chars (Telegram's limit is 4096).
3. APScheduler `AsyncIOScheduler` with a `SQLAlchemyJobStore` on its own SQLite file
   so jobs survive restarts. Job functions must be module-level (jobstore pickles them);
   pass only scalar args.

Use uv + pyproject for dependency management. Entrypoint: `uv run python -m app.main`,
which starts all three and shuts them down cleanly on SIGINT.

**Storage.** SQLAlchemy 2.0 declarative models on SQLite, one `data/` directory holding
all state. Provide `init_db(db_path)` (idempotent: engine + create_all + migrations),
a `get_session()` contextmanager (commit/rollback/close), and a `_migrate(engine)` that
adds missing columns via `PRAGMA table_info` + `ALTER TABLE` (migrations-lite — no alembic).
Important: SQLite returns naive datetimes — provide `as_utc(dt)` that re-attaches UTC,
and use it before every datetime comparison or isoformat serialization.

**Config.** pydantic-settings `Settings` class reading `.env`, with `extra="allow"` so
dynamically named env vars (e.g. `GMAIL_<NAME>_REFRESH_TOKEN`) are accessible via
`settings.model_extra`. When reading those, prefer real `os.environ` over model_extra
(docker/CI injects real env vars). Cache with `@lru_cache get_settings()`.

**LLM provider factory.** `get_chat_model(role, settings)` returning a LangChain
`BaseChatModel`, where role ∈ {classify, draft, chat} maps to a per-role model setting.
Global `MODEL_PROVIDER` selects gemini/anthropic/groq; a model string may override it
with a `provider/model` prefix (split on first `/` only if the prefix is a known
provider). Also provide `extract_text(content)` that flattens LangChain message content
that may be a list of content blocks (Gemini does this) into a plain string.

**Security defaults.**
- The agent/chat layer must have NO tool that sends anything to external parties;
  outbound actions happen only via explicit human action through the API.
- All third-party content fed to LLMs gets wrapped in named delimiter tags with an
  instruction that it is data, not instructions (prompt-injection defense).
- Secrets only via env / .env (gitignored); ship a `.env.example`.

**Verification.** pytest suite with a per-test temp-SQLite fixture; tests must not
require network or real API keys (fake LLM objects implementing
`with_structured_output(schema).invoke(prompt)`).
