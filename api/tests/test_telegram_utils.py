"""Tests for telegram_bot chunking helper."""

from app.channels.telegram import TELEGRAM_MAX_LEN, chunk_text


def test_short_text_single_chunk():
    assert chunk_text("hello") == ["hello"]

def test_long_text_split_within_limit():
    text = "x" * (TELEGRAM_MAX_LEN * 2 + 100)
    chunks = chunk_text(text)
    assert len(chunks) == 3
    assert all(len(c) <= TELEGRAM_MAX_LEN for c in chunks)
    assert "".join(chunks) == text

def test_prefers_newline_boundaries():
    line = "email line\n"
    text = line * 800  # well over one chunk
    chunks = chunk_text(text)
    assert all(len(c) <= TELEGRAM_MAX_LEN for c in chunks)
    # splits land on line boundaries, not mid-line
    assert all(c.endswith("\n") or c == chunks[-1] for c in chunks)


async def test_notify_owner_closes_bot(monkeypatch):
    """notify_owner must enter/exit the Bot context (closing its httpx pool)."""
    import telegram
    from app.channels import telegram as tg

    closed = {"v": False}
    sent: list[str] = []

    class FakeBot:
        def __init__(self, token):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            closed["v"] = True
        async def send_message(self, chat_id, text):
            sent.append(text)

    monkeypatch.setattr(telegram, "Bot", FakeBot)
    await tg.notify_owner("hello there")
    assert sent == ["hello there"]
    assert closed["v"] is True  # pool was shut down
