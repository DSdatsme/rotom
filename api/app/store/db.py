"""SQLite persistence: triaged emails, reply drafts, processed-message dedup."""

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import DateTime, Engine, ForeignKey, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; re-attach UTC so comparisons/ISO output are safe."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


class Category(StrEnum):
    CRITICAL = "critical"
    NEEDS_REPLY = "needs_reply"
    FYI = "fyi"
    SKIP = "skip"


class DraftKind(StrEnum):
    REPLY = "reply"
    OUTREACH = "outreach"


class DraftStatus(StrEnum):
    PENDING = "pending"
    SENDING = "sending"  # committed intent before the irreversible Gmail send (at-most-once guard)
    SENT = "sent"
    DISCARDED = "discarded"


class CodingStatus(StrEnum):
    RUNNING = "running"
    REVIEW = "review"
    BLOCKED = "blocked"
    DONE = "done"
    FAILED = "failed"


class EmailStatus(StrEnum):
    OPEN = "open"
    DONE = "done"  # user has taken care of it
    IRRELEVANT = "irrelevant"  # user marked it as noise


class ReminderStatus(StrEnum):
    PENDING = "pending"
    FIRED = "fired"
    CANCELLED = "cancelled"


class Email(Base):
    __tablename__ = "emails"
    __table_args__ = (UniqueConstraint("account", "message_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[str] = mapped_column(String(64))
    message_id: Mapped[str] = mapped_column(String(128))  # Gmail message id
    thread_id: Mapped[str] = mapped_column(String(128), default="")
    sender: Mapped[str] = mapped_column(String(512), default="")
    subject: Mapped[str] = mapped_column(String(1024), default="")
    snippet: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    rfc_message_id: Mapped[str] = mapped_column(String(512), default="")
    references: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(32), default=Category.FYI)
    status: Mapped[str] = mapped_column(String(32), default=EmailStatus.OPEN, server_default="open")
    suspicious: Mapped[bool] = mapped_column(default=False, server_default="0")
    urgency: Mapped[int] = mapped_column(default=0)  # 0 low … 3 urgent
    reason: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    drafts: Mapped[list["Draft"]] = relationship(back_populates="email")


class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), default=DraftKind.REPLY)
    email_id: Mapped[int | None] = mapped_column(ForeignKey("emails.id"), nullable=True)
    account: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_addr: Mapped[str | None] = mapped_column(String(512), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(998), nullable=True)
    body: Mapped[str] = mapped_column(Text, default="")
    attachments: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of keys
    gmail_draft_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=DraftStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    email: Mapped["Email | None"] = relationship(back_populates="drafts")
    messages: Mapped[list["DraftMessage"]] = relationship(
        back_populates="draft", order_by="DraftMessage.created_at",
        cascade="all, delete-orphan",
    )


class CodingRun(Base):
    __tablename__ = "coding_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    issue_url: Mapped[str] = mapped_column(String(512))
    repo: Mapped[str] = mapped_column(String(255))
    issue_number: Mapped[int] = mapped_column()
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pr_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    claude_session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    worktree_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=CodingStatus.RUNNING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DraftMessage(Base):
    __tablename__ = "draft_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id"))
    role: Mapped[str] = mapped_column(String(16))  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    draft: Mapped["Draft"] = relationship(back_populates="messages")


class Reminder(Base):
    """A one-time or recurring reminder, fired to Telegram by the scheduler."""

    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    fire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # UTC; first/next occurrence
    recurrence_cron: Mapped[str] = mapped_column(String(64), default="")  # crontab expr; "" = one-time
    status: Mapped[str] = mapped_column(String(32), default=ReminderStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProcessedMessage(Base):
    """Dedup ledger: every Gmail message id we've already triaged."""

    __tablename__ = "processed_messages"
    __table_args__ = (UniqueConstraint("account", "message_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[str] = mapped_column(String(64))
    message_id: Mapped[str] = mapped_column(String(128))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def apply_sqlite_pragmas(engine: Engine) -> None:
    """Put a SQLite engine into WAL with a busy_timeout, on every connection.

    rotom writes one SQLite file from the event loop, worker threads, AND daemon
    threads. In the default rollback-journal mode a write takes an exclusive lock
    and a competing writer fails *immediately* with 'database is locked'. WAL lets
    readers run concurrently with one writer; busy_timeout makes a competing writer
    wait-and-retry (up to 5s) instead of erroring. synchronous=NORMAL is safe + fast
    under WAL.
    """
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()


def init_db(db_path: str) -> Engine:
    """Create the engine, tables, and session factory. Idempotent."""
    global _engine, _session_factory
    if _engine is None:
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        _engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        apply_sqlite_pragmas(_engine)
        Base.metadata.create_all(_engine)
        _migrate(_engine)
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def _migrate(engine: Engine) -> None:
    """Migrations-lite: add columns that create_all won't add to existing tables."""
    from sqlalchemy import text

    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(emails)"))}
        if "status" not in cols:
            conn.execute(text("ALTER TABLE emails ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'open'"))
        if "suspicious" not in cols:
            conn.execute(text("ALTER TABLE emails ADD COLUMN suspicious BOOLEAN NOT NULL DEFAULT 0"))

        draft_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(drafts)"))}
        if draft_cols:
            if "kind" not in draft_cols:
                conn.execute(text("ALTER TABLE drafts ADD COLUMN kind VARCHAR(16) NOT NULL DEFAULT 'reply'"))
            if "account" not in draft_cols:
                conn.execute(text("ALTER TABLE drafts ADD COLUMN account VARCHAR(64)"))
            if "to_addr" not in draft_cols:
                conn.execute(text("ALTER TABLE drafts ADD COLUMN to_addr VARCHAR(512)"))
            if "subject" not in draft_cols:
                conn.execute(text("ALTER TABLE drafts ADD COLUMN subject VARCHAR(998)"))
            if "attachments" not in draft_cols:
                conn.execute(text("ALTER TABLE drafts ADD COLUMN attachments TEXT NOT NULL DEFAULT '[]'"))
            if "gmail_draft_id" not in draft_cols:
                conn.execute(text("ALTER TABLE drafts ADD COLUMN gmail_draft_id VARCHAR(128)"))

            # Normalize legacy rows: older code stored "" for an unset
            # recipient/account; NULL is the single "unset" sentinel now
            # (reply drafts derive both from the source email). Idempotent.
            conn.execute(text("UPDATE drafts SET to_addr = NULL WHERE to_addr = ''"))
            conn.execute(text("UPDATE drafts SET account = NULL WHERE account = ''"))


def reset_db() -> None:
    """Drop engine/session state (used by tests)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


@contextmanager
def get_session():
    if _session_factory is None:
        raise RuntimeError("init_db() must be called before get_session()")
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
