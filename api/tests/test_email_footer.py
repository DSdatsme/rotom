"""Tests for the 'Sent with rotom' footer builders and build_mime integration."""

import base64
from email import message_from_bytes

from app.tools.gmail.footer import plain_footer, html_body

URL = "https://rotom.example.com"


def test_plain_footer_has_phrase_and_url():
    out = plain_footer(URL)
    assert "Sent with rotom" in out
    assert URL in out
    assert out.startswith("\n\n")


def test_html_body_escapes_body_and_has_single_anchor():
    out = html_body("hi <script>alert(1)</script>\nsecond line", URL)
    assert "&lt;script&gt;" in out
    assert "<script>" not in out
    assert out.count("<a ") == 1
    assert f'href="{URL}"' in out
    assert "Sent with" in out


def test_html_body_converts_newlines_to_br():
    out = html_body("line one\nline two", URL)
    assert "<br>" in out
    assert "line one" in out and "line two" in out


def _decode(raw):
    return message_from_bytes(base64.urlsafe_b64decode(raw))


def test_build_mime_no_footer_is_plain_text():
    from app.tools.gmail.client import build_mime
    msg = _decode(build_mime("r@x.com", "Hello", "Hi there"))
    assert msg.get_content_type() == "text/plain"


def test_build_mime_with_footer_is_multipart_alternative():
    from app.tools.gmail.client import build_mime
    msg = _decode(build_mime("r@x.com", "Hello", "Hi there", footer_url=URL))
    assert msg.get_content_type() == "multipart/alternative"
    types = {p.get_content_type() for p in msg.walk()}
    assert "text/plain" in types and "text/html" in types
    html_part = next(p for p in msg.walk() if p.get_content_type() == "text/html")
    plain_part = next(p for p in msg.walk() if p.get_content_type() == "text/plain")
    assert URL in html_part.get_payload(decode=True).decode()
    assert URL in plain_part.get_payload(decode=True).decode()


def test_build_mime_with_footer_and_attachment_is_mixed(tmp_path):
    from app.tools.gmail.client import build_mime
    f = tmp_path / "resume.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    msg = _decode(build_mime("r@x.com", "Role", "See attached",
                             attachments=[str(f)], footer_url=URL))
    assert msg.get_content_type() == "multipart/mixed"
    subtypes = {p.get_content_type() for p in msg.walk()}
    assert "multipart/alternative" in subtypes
    names = [p.get_filename() for p in msg.walk() if p.get_filename()]
    assert "resume.pdf" in names


def test_settings_have_footer_defaults():
    from app.config import Settings
    s = Settings()
    assert s.email_footer_enabled is True
    assert s.email_footer_url == ""
