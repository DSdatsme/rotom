"""_migrate adds new columns to pre-existing tables."""

from sqlalchemy import create_engine, text

from app.store.db import _migrate


def test_migrate_adds_suspicious(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/m.db")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE emails (id INTEGER PRIMARY KEY, status VARCHAR(32) NOT NULL DEFAULT 'open')"))
    _migrate(engine)
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(emails)"))}
    assert "suspicious" in cols

def test_draft_new_columns_and_messages_table(tmp_path):
    from app.store.db import init_db, get_session, Draft, DraftMessage, DraftKind
    init_db(str(tmp_path / "t.db"))  # match existing init signature in this file
    with get_session() as s:
        d = Draft(kind=DraftKind.OUTREACH, body="hi", to_addr="r@x.com",
                  subject="Hello", account="main", attachments="[]")
        s.add(d); s.flush()
        s.add(DraftMessage(draft_id=d.id, role="user", content="draft an email"))
        s.flush()
        assert d.email_id is None
        assert d.gmail_draft_id is None
        assert len(d.messages) == 1



def test_sqlite_pragmas_wal_and_busy_timeout(tmp_path):
    """Both engines must run in WAL with a busy_timeout so concurrent writers
    wait-and-retry instead of failing instantly with 'database is locked'."""
    from app.store import db
    db.reset_db()
    engine = db.init_db(str(tmp_path / "p.db"))
    with engine.connect() as c:
        assert c.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert c.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000
    db.reset_db()
