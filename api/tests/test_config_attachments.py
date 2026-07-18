import pytest
from app.config import parse_attachments, resolve_attachments, AttachmentMeta

def test_parse_attachments():
    metas = parse_attachments("resume:My Résumé:./data/a/resume.pdf, port:Portfolio:./p.pdf")
    assert metas == [
        AttachmentMeta("resume", "My Résumé", "./data/a/resume.pdf"),
        AttachmentMeta("port", "Portfolio", "./p.pdf"),
    ]

def test_parse_attachments_empty():
    assert parse_attachments("") == []

def test_resolve_selected_keys(tmp_path):
    f = tmp_path / "resume.pdf"; f.write_text("x")
    metas = [AttachmentMeta("resume", "Résumé", str(f))]
    assert resolve_attachments(["resume"], metas) == [str(f)]

def test_resolve_missing_file_raises(tmp_path):
    metas = [AttachmentMeta("resume", "Résumé", str(tmp_path / "nope.pdf"))]
    with pytest.raises(FileNotFoundError):
        resolve_attachments(["resume"], metas)

def test_resolve_unknown_key_raises():
    with pytest.raises(KeyError):
        resolve_attachments(["ghost"], [])
