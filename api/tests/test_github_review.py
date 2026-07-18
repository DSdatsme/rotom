from app.tools.github import review as R


def test_reviewers_roster_has_general_and_security():
    names = {r["name"] for r in R.REVIEWERS}
    assert {"reviewer", "security"} <= names
    for r in R.REVIEWERS:
        assert r["prompt"]  # non-empty lens prompt


def test_build_review_prompt_embeds_diff_and_lens():
    p = R.build_review_prompt({"name": "security", "prompt": "Look for injection."}, "diff --git a b")
    assert "Look for injection." in p
    assert "diff --git a b" in p


def test_parse_findings_valid_json():
    raw = '{"findings": [{"severity": "high", "title": "X", "detail": "y"}]}'
    out = R.parse_findings(raw)
    assert out == [{"severity": "high", "title": "X", "detail": "y"}]


def test_parse_findings_wrapped_in_text():
    raw = 'Here you go:\n```json\n{"findings": []}\n```\nthanks'
    assert R.parse_findings(raw) == []


def test_parse_findings_malformed_returns_empty():
    assert R.parse_findings("not json at all") == []
    assert R.parse_findings("") == []
