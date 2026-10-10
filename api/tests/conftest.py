import os
import tempfile

import pytest

from app.store import db


@pytest.fixture()
def session_db():
    """Fresh SQLite DB per test."""
    db.reset_db()
    tmp = tempfile.mkdtemp()
    db.init_db(os.path.join(tmp, "test.db"))
    yield db
    db.reset_db()


def make_email(**overrides) -> dict:
    """A parsed-email dict as produced by gmail.client.parse_message."""
    base = {
        "account": "personal",
        "message_id": "m1",
        "thread_id": "t1",
        "sender": "Alice <alice@example.com>",
        "subject": "Hello",
        "snippet": "snippet text",
        "body": "body text",
        "rfc_message_id": "<m1@mail>",
        "references": "",
        "received_at": None,
    }
    base.update(overrides)
    return base


@pytest.fixture()
def obs_db(tmp_path):
    """Fresh observability DB (tables + migrations + views) per test."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.store import observability as obs

    engine = create_engine(f"sqlite:///{tmp_path / 'obs.db'}")
    obs.ObsBase.metadata.create_all(engine)
    obs._migrate(engine)
    obs._engine = engine
    obs._SessionFactory = sessionmaker(engine, expire_on_commit=False)
    yield obs
    obs._engine = None
    obs._SessionFactory = None


@pytest.fixture()
def traced(obs_db):
    """obs_db + a live TracerProvider exporting synchronously into the test DB."""
    from app.observability import tracing

    tracing.shutdown_tracing()
    tracing.init_tracing(simple=True)
    yield obs_db
    tracing.shutdown_tracing()


def span_rows(**filters):
    """All exported spans (ORM rows), optionally filtered by column equality."""
    from app.store.observability import Span, get_obs_session

    with get_obs_session() as s:
        q = s.query(Span)
        for col, value in filters.items():
            q = q.filter(getattr(Span, col) == value)
        return q.order_by(Span.start_time).all()
