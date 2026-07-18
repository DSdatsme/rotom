# Prompt — backend code conventions

> Paste into an AI coding agent before writing/editing Python services in this codebase.

---

Write Python (3.12) services in this codebase's style. Stack: FastAPI, SQLAlchemy 2.0,
pydantic-settings, APScheduler, LangChain/LangGraph (chat agent), Inngest (workflows),
uv. SQLite by default.

**Three execution shapes — pick the right one.** (1) *Deterministic pipeline* — heavy
repeatable jobs (triage): plain dependency-injected function, see below. (2) *Conversational
agent* — open-ended chat where the model picks tools: LangGraph `create_react_agent`. (3)
*Scheduled/triggered workflow* — fixed step pipeline on cron or manual event: an Inngest
function (`@inngest_client.create_function`, steps via `await ctx.step.run(id, async_fn)`).
These are separate engines; don't unify them. They share only `get_chat_model`.

**Config.** A pydantic-settings `Settings(BaseSettings)` with
`SettingsConfigDict(env_file=".env", extra="allow")` so dynamically named vars
(`GMAIL_<NAME>_REFRESH_TOKEN`) are reachable via `settings.model_extra`. When reading those,
prefer real `os.environ` over model_extra (docker/CI inject real env). Cache with
`@lru_cache get_settings()`. Secrets only from env — never literals in code.

**Storage.** SQLAlchemy 2.0 typed models (`Mapped[...]` / `mapped_column`). `init_db` is
idempotent (engine + `create_all` + a `_migrate()` that adds missing columns via
`PRAGMA table_info` + `ALTER TABLE` — migrations-lite, no alembic). A `get_session()`
contextmanager commits/rolls-back/closes. SQLite returns **naive** datetimes — provide
`utcnow()` and `as_utc(dt)` and apply `as_utc` before every comparison or `isoformat`.

**Pipelines over agents for deterministic work.** Heavy, repeatable jobs (e.g. triage) are
plain functions with **injected dependencies** — `run_x(fetchers, classify_fn, draft_fn,
...) -> Result` — not LLM agent loops. This makes them cron-callable, tool-callable, and
fully testable with fakes. A thin `service.py` wires real settings/LLMs and returns the
result; the pipeline core stays pure.

**Tools as packages.** Each capability is `app/tools/<name>/` with a `service.py` that wires
settings + LLMs and is the single entry point used by both cron jobs and agent tools.

**Workflows call helpers, never raw SDKs.** Inngest workflow files (`app/workflows/<name>.py`)
compose thin helpers from `app/workflows/lib.py` (`llm` / `run_script` / `notify`) inside
steps — never the LLM/subprocess/Telegram SDKs directly. The helper layer is the seam where
guardrails (call budgets, script allow-lists, log scrubbing) get retrofitted without touching
workflow files. One file per workflow, registered in `registry.py`.

**Agent tools = thin wrappers.** Inner logic is a plain, testable function (`*_text(...) ->
str`); the LangChain `@tool` wrapper only injects real dependencies. Docstrings are the
model's only API docs — make them precise (argument formats, side effects).

**Degraded state over exceptions.** In multi-item work (N accounts, N emails), one failure
must not abort the run: collect `errors[key] = msg` and continue, then surface failures in
the output. Failures are always visible, never silently swallowed.

**LLM access.** `get_chat_model(role)` with roles {classify, draft, chat}, each configurable;
provider chosen by `MODEL_PROVIDER` or a `provider/model` prefix. Structured output via
`llm.with_structured_output(PydanticSchema).invoke(prompt)` — and validate defensively
(missing fields default to safe values, don't crash). `extract_text(content)` flattens
content that may be a list of blocks. From async contexts, run sync SDK calls via
`asyncio.to_thread` so the event loop stays free.

**Scheduler.** APScheduler with a persistent `SQLAlchemyJobStore`. Job functions are
**module-level** and take only picklable scalar args (the jobstore pickles them). Use
`misfire_grace_time` so jobs fire after downtime; reconcile pending work at boot.

**Observability through one seam.** Wrap each autonomous unit of work in a `record_run(kind)`
context manager (own `observability.db`, separate from app data) that opens a `running` row,
propagates the run id via a `ContextVar`, captures the run's logs, and finalizes status on exit
(`failure` on raise or `run.fail()`). Writes go through a pluggable `ObservabilitySink` /
`QueryProvider` Protocol pair (factory off `OBSERVABILITY_BACKENDS`) so an external backend is a
drop-in — never hardcode the store at call sites. LLM token+latency capture is a LangChain
callback that records through the sink; logging is structured JSON (one object per line,
run_id-stamped) with a buffered, reentrancy-safe DB handler. This is independent of the execution
engine: it gives the scheduler, API, and (later) Inngest paths one unified run/usage/log surface.
Interactive chat turns stay adhoc (no run row).

**Tests** (pytest): a per-test temp-SQLite fixture (`init_db` into a tmpdir, reset after);
**no network or real API keys** — inject fake LLMs implementing `with_structured_output(
schema).invoke(prompt)` and fake fetchers/schedulers. Assert zero LLM calls on the
deterministic paths (dedup, rules, shorthands).
