import os
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from app.config import get_settings
from app.observability import semconv as sc


class ObsBase(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    # The core work completed, but a non-critical part didn't (e.g. per-account
    # fetch errors, or the digest couldn't be delivered). Not a clean success,
    # not a hard failure — surfaced as a warning.
    DEGRADED = "degraded"
    # Terminal "we lost track of this run" — the process died mid-run before a
    # clean finish (crash, deploy, laptop sleep). Set by the stale-run reaper.
    INTERRUPTED = "interrupted"


class RunLog(ObsBase):
    __tablename__ = "run_log"
    __table_args__ = (
        Index("ix_run_log_parent_run_id", "parent_run_id"),
        Index("ix_run_log_trace_id", "trace_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(64))
    # Unify run sources — the two facets:
    #   source = how it was initiated (scheduler | manual | chat | inngest | system)
    source: Mapped[str] = mapped_column(String(32), default="system")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=RunStatus.RUNNING)
    summary: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    logs: Mapped[str] = mapped_column(Text, default="")
    # External engine linkage (e.g. Inngest) — link-only in v1.
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Automatic parent/child nesting (loose self-reference, no hard FK).
    parent_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Bumped while a run is open; powers the stale-run reaper.
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # OTel trace this run's root span belongs to (NULL for pre-tracing runs).
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    usages: Mapped[list["LLMUsage"]] = relationship()


class LLMUsage(ObsBase):
    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("run_log.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(32), default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    role: Mapped[str] = mapped_column(String(32), default="")
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    # Feature B: per-call LLM latency in milliseconds (nullable for back-compat)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class LogEntry(ObsBase):
    """Centralised log store for the Logs Explorer (Feature A).

    All structured fields are nullable/optional except ts+level+msg.
    run_id is intentionally a loose integer reference (no FK constraint)
    so logs written outside a run context are always accepted.
    """
    __tablename__ = "log_entry"
    __table_args__ = (
        Index("ix_log_entry_ts", "ts"),
        Index("ix_log_entry_run_id", "run_id"),
        Index("ix_log_entry_trace_id", "trace_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    level: Mapped[str] = mapped_column(String(16))
    logger: Mapped[str] = mapped_column(String(128), default="")
    msg: Mapped[str] = mapped_column(Text, default="")
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extra: Mapped[str] = mapped_column(Text, default="{}")  # JSON string
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    span_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    exc_info: Mapped[str | None] = mapped_column(Text, nullable=True)


class Span(ObsBase):
    """One finished OTel span. GenAI hot fields are promoted to columns; everything
    else stays in `attributes` (JSON). `trace_id` is NULL only for backfilled v1 LLM rows."""
    __tablename__ = "span"
    __table_args__ = (
        Index("ix_span_trace_id", "trace_id"),
        Index("ix_span_start_time", "start_time"),
        Index("ix_span_run_id", "run_id"),
        Index("ix_span_operation", "operation"),
    )

    span_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    parent_span_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    name: Mapped[str] = mapped_column(String(256))
    span_kind: Mapped[str] = mapped_column(String(16), default="INTERNAL")
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(8), default="UNSET")
    status_message: Mapped[str] = mapped_column(Text, default="")
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    operation: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    attributes: Mapped[str] = mapped_column(Text, default="{}")
    events: Mapped[str] = mapped_column(Text, default="[]")


class ObsMeta(ObsBase):
    """Key/value markers: one-time migrations done, followed semconv version."""
    __tablename__ = "obs_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


_engine = None
_SessionFactory = None

def create_all():
    global _engine, _SessionFactory
    if _engine is None:
        settings = get_settings()
        os.makedirs(settings.data_dir, exist_ok=True)
        # Using a sync engine, same as rotom.db sync operations
        # Path might be relative, e.g. ./data/observability.db
        # We need an absolute path for sqlite://// or just use sqlite:/// relative
        db_path = settings.observability_db_path
        if not db_path.startswith("/"):
            db_path = os.path.abspath(db_path)
        _engine = create_engine(f"sqlite:///{db_path}")
        from app.store.db import apply_sqlite_pragmas
        apply_sqlite_pragmas(_engine)  # WAL + busy_timeout: this DB is written from many threads
        ObsBase.metadata.create_all(_engine)
        _migrate(_engine)
        _prune_old_logs(_engine, settings.log_retention_days)
        _prune_old_spans(_engine, settings.trace_retention_days)
        _SessionFactory = sessionmaker(_engine, expire_on_commit=False)


def _migrate(engine) -> None:
    """Migrations-lite: add new columns to existing tables without dropping data."""
    from sqlalchemy import text

    with engine.begin() as conn:
        # Feature B: add latency_ms to llm_usage
        usage_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(llm_usage)"))}
        if "latency_ms" not in usage_cols:
            conn.execute(text("ALTER TABLE llm_usage ADD COLUMN latency_ms INTEGER"))

        # Unify run sources: additive columns on run_log (existing rows get
        # source='system', null external/parent/heartbeat).
        run_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(run_log)"))}
        run_additions = {
            "source": "ALTER TABLE run_log ADD COLUMN source VARCHAR(32) DEFAULT 'system'",
            "external_id": "ALTER TABLE run_log ADD COLUMN external_id VARCHAR(128)",
            "external_url": "ALTER TABLE run_log ADD COLUMN external_url TEXT",
            "parent_run_id": "ALTER TABLE run_log ADD COLUMN parent_run_id INTEGER",
            "last_heartbeat_at": "ALTER TABLE run_log ADD COLUMN last_heartbeat_at DATETIME",
            "trace_id": "ALTER TABLE run_log ADD COLUMN trace_id VARCHAR(32)",
        }
        for col, ddl in run_additions.items():
            if col not in run_cols:
                conn.execute(text(ddl))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_run_log_parent_run_id ON run_log (parent_run_id)"
        ))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_run_log_trace_id ON run_log (trace_id)"))

        log_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(log_entry)"))}
        log_additions = {
            "trace_id": "ALTER TABLE log_entry ADD COLUMN trace_id VARCHAR(32)",
            "span_id": "ALTER TABLE log_entry ADD COLUMN span_id VARCHAR(16)",
            "exc_info": "ALTER TABLE log_entry ADD COLUMN exc_info TEXT",
        }
        for col, ddl in log_additions.items():
            if col not in log_cols:
                conn.execute(text(ddl))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_log_entry_trace_id ON log_entry (trace_id)"))

        _scrub_secrets(conn)
        _backfill_llm_usage(conn)

        from app.observability.semconv import SEMCONV_VERSION

        _meta_set(conn, "genai.semconv_version", SEMCONV_VERSION)
        _create_views(conn)


def json_attr(key: str, col: str = "attributes") -> str:
    """SQL expression extracting one span attribute; `key` must be a semconv constant."""
    return f"json_extract({col}, '$.\"{key}\"')"


# Shared by v_traces and queries.traces() so the trace taxonomy/aggregates live in one place.
TRACE_TYPE_SQL = (
    f"CASE WHEN {json_attr(sc.ROTOM_RUN_KIND, 'root.attributes')} IS NOT NULL THEN 'run' "
    f"WHEN root.operation = '{sc.OP_INVOKE_AGENT}' THEN 'chat' "
    "WHEN root.span_kind = 'SERVER' THEN 'http' ELSE 'other' END"
)
TRACE_AGG_COLUMNS = (
    f"COUNT(*) AS span_count, SUM(operation = '{sc.OP_CHAT}') AS llm_calls, "
    "COALESCE(SUM(input_tokens), 0) AS input_tokens, COALESCE(SUM(output_tokens), 0) AS output_tokens, "
    "SUM(cost_usd) AS cost_usd, SUM(status = 'ERROR') AS error_count"
)

# The SQL query surface (see docs/observability/QUERIES.md). Recreated on every startup
# so definition changes ship with the code.
_VIEWS = {
    "v_runs": f"""
        SELECT r.id AS run_id, r.kind, r.source, r.status, r.started_at, r.finished_at,
               (julianday(r.finished_at) - julianday(r.started_at)) * 86400000.0 AS duration_ms,
               r.summary, r.error, r.trace_id, r.parent_run_id,
               COALESCE(u.llm_calls, 0) AS llm_calls,
               COALESCE(u.input_tokens, 0) AS input_tokens,
               COALESCE(u.output_tokens, 0) AS output_tokens,
               u.cost_usd, COALESCE(u.error_spans, 0) AS error_spans
        FROM run_log r
        LEFT JOIN (
            SELECT run_id, SUM(operation = '{sc.OP_CHAT}') AS llm_calls, SUM(input_tokens) AS input_tokens,
                   SUM(output_tokens) AS output_tokens, SUM(cost_usd) AS cost_usd,
                   SUM(status = 'ERROR') AS error_spans
            FROM span WHERE run_id IS NOT NULL GROUP BY run_id
        ) u ON u.run_id = r.id""",
    "v_traces": f"""
        SELECT root.trace_id, root.span_id AS root_span_id, root.name AS root_name,
               {TRACE_TYPE_SQL} AS trace_type,
               root.start_time, root.duration_ms, root.run_id, root.status,
               {json_attr(sc.ROTOM_RUN_STATUS, 'root.attributes')} AS run_status,
               agg.span_count, agg.llm_calls, agg.input_tokens, agg.output_tokens,
               agg.cost_usd, agg.error_count
        FROM span root
        JOIN (
            SELECT trace_id, {TRACE_AGG_COLUMNS}
            FROM span WHERE trace_id IS NOT NULL GROUP BY trace_id
        ) agg ON agg.trace_id = root.trace_id
        WHERE root.parent_span_id IS NULL AND root.trace_id IS NOT NULL""",
    "v_llm_calls": f"""
        SELECT s.span_id, s.trace_id, s.parent_span_id, s.run_id, r.kind AS run_kind,
               s.start_time, s.duration_ms, s.status, s.status_message, s.provider, s.model,
               {json_attr(sc.ROTOM_LLM_ROLE, 's.attributes')} AS role,
               s.input_tokens, s.output_tokens, s.cache_read_tokens, s.reasoning_tokens, s.cost_usd,
               {json_attr(sc.RESPONSE_FINISH_REASONS, 's.attributes')} AS finish_reasons,
               {json_attr(sc.INPUT_MESSAGES, 's.attributes')} AS input_messages,
               {json_attr(sc.OUTPUT_MESSAGES, 's.attributes')} AS output_messages
        FROM span s LEFT JOIN run_log r ON r.id = s.run_id
        WHERE s.operation = '{sc.OP_CHAT}'""",
    "v_tool_calls": f"""
        SELECT s.span_id, s.trace_id, s.parent_span_id, s.run_id, s.start_time, s.duration_ms, s.status,
               {json_attr(sc.TOOL_NAME, 's.attributes')} AS tool,
               {json_attr(sc.TOOL_CALL_ARGUMENTS, 's.attributes')} AS arguments,
               {json_attr(sc.TOOL_CALL_RESULT, 's.attributes')} AS result
        FROM span s WHERE s.operation = '{sc.OP_EXECUTE_TOOL}'""",
    "v_errors": """
        SELECT 'span' AS source, s.start_time AS ts, s.trace_id, s.span_id, s.run_id,
               s.name AS what, s.status_message AS message
        FROM span s WHERE s.status = 'ERROR'
        UNION ALL
        SELECT 'log', l.ts, l.trace_id, l.span_id, l.run_id, l.logger,
               l.msg || COALESCE(char(10) || l.exc_info, '')
        FROM log_entry l WHERE l.level IN ('ERROR', 'CRITICAL')""",
}


def _create_views(conn) -> None:
    from sqlalchemy import text

    for name, select_sql in _VIEWS.items():
        conn.execute(text(f"DROP VIEW IF EXISTS {name}"))
        conn.execute(text(f"CREATE VIEW {name} AS {select_sql}"))


def _meta_get(conn, key: str) -> str | None:
    from sqlalchemy import text

    row = conn.execute(text("SELECT value FROM obs_meta WHERE key = :k"), {"k": key}).first()
    return row[0] if row else None


def _meta_set(conn, key: str, value: str) -> None:
    from sqlalchemy import text

    conn.execute(
        text("INSERT INTO obs_meta (key, value) VALUES (:k, :v) "
             "ON CONFLICT(key) DO UPDATE SET value = excluded.value"),
        {"k": key, "v": value},
    )


# Columns that v1 may have persisted with secrets in them.
_SCRUB_COLUMNS = {"log_entry": ("msg", "extra"), "run_log": ("logs", "error", "summary")}


def _scrub_secrets(conn) -> None:
    """One-time: mask secret values v1 persisted unredacted (httpx logged Telegram URLs
    containing the bot token). New rows are redacted at write time by log_schema."""
    from sqlalchemy import text

    from app.observability.redact import MASK, secret_values

    if _meta_get(conn, "scrub.secrets.v1"):
        return
    for value in secret_values():
        for table, cols in _SCRUB_COLUMNS.items():
            for col in cols:
                conn.execute(
                    text(f"UPDATE {table} SET {col} = replace({col}, :v, :m) WHERE instr({col}, :v) > 0"),
                    {"v": value, "m": MASK},
                )
    _meta_set(conn, "scrub.secrets.v1", utcnow().isoformat())


def _backfill_llm_usage(conn) -> None:
    """One-time: copy v1 `llm_usage` rows into `span` (operation='chat', trace_id NULL —
    they predate tracing) so LLM stats/cost cover history. llm_usage is no longer written."""
    import json
    from datetime import timedelta

    from sqlalchemy import insert, select

    from app.observability import semconv as sc
    from app.observability.pricing import cost_usd

    if _meta_get(conn, "backfill.llm_usage.v1"):
        return
    rows = []
    for u in conn.execute(select(LLMUsage.__table__)).mappings():
        end = u["ts"]
        if end is not None and end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        duration = float(u["latency_ms"] or 0)
        rows.append({
            "span_id": f"l{u['id']:015d}",
            "trace_id": None,
            "parent_span_id": None,
            "name": f"chat {u['model']}",
            "span_kind": "CLIENT",
            "start_time": end - timedelta(milliseconds=duration),
            "end_time": end,
            "duration_ms": duration,
            "status": "UNSET",
            "status_message": "",
            "run_id": u["run_id"],
            "operation": sc.OP_CHAT,
            "provider": sc.PROVIDER_NAMES.get(u["provider"], u["provider"]),
            "model": u["model"],
            "input_tokens": u["input_tokens"],
            "output_tokens": u["output_tokens"],
            "cost_usd": cost_usd(u["provider"], u["model"], input_tokens=u["input_tokens"],
                                 output_tokens=u["output_tokens"]),
            "attributes": json.dumps({sc.ROTOM_LLM_ROLE: u["role"], sc.ROTOM_LEGACY: True}),
            "events": "[]",
        })
    if rows:
        conn.execute(insert(Span.__table__).prefix_with("OR IGNORE"), rows)
    _meta_set(conn, "backfill.llm_usage.v1", utcnow().isoformat())


def _prune_old_logs(engine, retention_days: int) -> None:
    """Delete LogEntry rows older than retention_days (0 = keep everything)."""
    _prune(engine, LogEntry, LogEntry.ts, retention_days)


def _prune_old_spans(engine, retention_days: int) -> None:
    """Delete span rows older than retention_days (0 = keep everything)."""
    _prune(engine, Span, Span.end_time, retention_days)


def _prune(engine, model, column, retention_days: int) -> None:
    from datetime import timedelta

    from sqlalchemy import delete
    from sqlalchemy.orm import Session

    if retention_days <= 0:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    with Session(engine) as session:
        session.execute(delete(model).where(column < cutoff))
        session.commit()


def prune_observability() -> None:
    """Apply LOG_RETENTION_DAYS / TRACE_RETENTION_DAYS (startup + daily job)."""
    if _engine is None:
        create_all()
    settings = get_settings()
    _prune_old_logs(_engine, settings.log_retention_days)
    _prune_old_spans(_engine, settings.trace_retention_days)


@contextmanager
def get_obs_session():
    if _SessionFactory is None:
        create_all()
    with _SessionFactory() as session:
        yield session
