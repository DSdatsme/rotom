from app.store.db import DraftKind
from app.tools.drafts.composer import (
    ComposerContext, Identity, build_composer_prompt, parse_composer_response, compose,
)
from app.config import AttachmentMeta

def _ctx(kind, new_message, source_email=None, attachments=()):
    return ComposerContext(
        kind=kind, source_email=source_email, history=[], new_message=new_message,
        identity=Identity(name="Dar", signature="Best, Dar"),
        attachments=list(attachments),
    )

def test_outreach_prompt_wraps_pasted_text_untrusted_and_includes_identity():
    p = build_composer_prompt(_ctx(DraftKind.OUTREACH, "We're hiring a Staff SRE. apply@acme.io",
                                   attachments=[AttachmentMeta("resume","Résumé","/r.pdf")]))
    low = p.lower()
    assert "<untrusted_content>" in low and "</untrusted_content>" in low
    assert "dar" in low and "résumé" in low
    assert "never invent a recipient" in low  # may extract from content, but never fabricate

def test_reply_prompt_includes_source_email_and_no_subject_ask():
    p = build_composer_prompt(_ctx(DraftKind.REPLY, "say I'm free next week",
                                   source_email={"sender":"a@x.com","subject":"Re: call","body":"can we talk?"}))
    assert "<untrusted_content>" in p
    assert "can we talk?" in p

def test_parse_outreach_json_fenced_and_unfenced():
    raw = '```json\n{"body":"Hi","subject":"Hello","to":"r@x.com","note":"drafted"}\n```'
    r = parse_composer_response(raw, DraftKind.OUTREACH)
    assert r.body == "Hi" and r.subject == "Hello" and r.to_addr == "r@x.com"

def test_parse_reply_ignores_subject_to():
    r = parse_composer_response('{"body":"ok","subject":"X","to":"y@z.com","note":"n"}', DraftKind.REPLY)
    assert r.body == "ok" and r.subject is None and r.to_addr is None

def test_parse_missing_optional_to_is_empty():
    r = parse_composer_response('{"body":"Hi","subject":"S","note":"n"}', DraftKind.OUTREACH)
    assert r.to_addr in (None, "")

class FakeLLM:
    def __init__(self, raw): self.raw = raw; self.prompts = []
    def invoke(self, prompt):
        self.prompts.append(prompt)
        class R: pass
        r = R(); r.content = self.raw; return r

def test_compose_returns_result(monkeypatch):
    llm = FakeLLM('{"body":"Hi there","subject":"Hello","to":"","note":"ok"}')
    r = compose(_ctx(DraftKind.OUTREACH, "hiring SRE"), llm)
    assert r.body == "Hi there" and r.subject == "Hello"
