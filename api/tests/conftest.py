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
