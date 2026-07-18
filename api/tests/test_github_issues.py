"""Tests for GitHub coding-agent config + pure issue helpers."""


def test_coding_agent_repo_list_parses_and_strips():
    from app.config import Settings
    s = Settings(coding_agent_repos="DSdatsme/rotom, owner/repo2 ,")
    assert s.coding_agent_repo_list == ["DSdatsme/rotom", "owner/repo2"]


def test_coding_agent_repo_list_empty():
    from app.config import Settings
    assert Settings(coding_agent_repos="").coding_agent_repo_list == []


def test_coding_agent_defaults():
    from app.config import Settings
    s = Settings()
    assert s.coding_agent_max_turns == 30
    assert s.coding_agent_max_fix_rounds == 2
    assert s.coding_agent_sandbox_image == "rotom-coding:latest"


import pytest
from app.tools.github import issues as I


@pytest.mark.parametrize("url,expected", [
    ("https://github.com/DSdatsme/rotom/issues/12", ("DSdatsme", "rotom", 12)),
    ("https://github.com/owner/repo/issues/3#issuecomment-1", ("owner", "repo", 3)),
    ("http://github.com/a/b/issues/9", ("a", "b", 9)),
])
def test_parse_issue_url_valid(url, expected):
    assert I.parse_issue_url(url) == expected


@pytest.mark.parametrize("url", [
    "https://github.com/DSdatsme/rotom/pull/12",
    "https://github.com/DSdatsme/rotom",
    "not a url",
    "https://gitlab.com/a/b/issues/1",
])
def test_parse_issue_url_invalid(url):
    with pytest.raises(ValueError):
        I.parse_issue_url(url)


def test_is_allowed_repo():
    allow = ["DSdatsme/rotom", "Org/Repo"]
    assert I.is_allowed_repo("DSdatsme", "rotom", allow) is True
    assert I.is_allowed_repo("org", "repo", allow) is True   # case-insensitive
    assert I.is_allowed_repo("evil", "repo", allow) is False


def test_build_task_prompt_includes_issue():
    p = I.build_task_prompt("Fix the bug", "Steps: do X", test_cmd="pytest -q")
    assert "Fix the bug" in p and "do X" in p and "pytest -q" in p


def test_build_pr_body_links_issue():
    body = I.build_pr_body("https://github.com/DSdatsme/rotom/issues/12")
    assert "https://github.com/DSdatsme/rotom/issues/12" in body
    assert "rotom" in body.lower()


def test_build_findings_comment_groups_by_reviewer():
    out = I.build_findings_comment([
        ("reviewer", [{"severity": "high", "title": "Null deref", "detail": "line 5"}]),
        ("security", []),
    ])
    assert "Null deref" in out and "high" in out.lower()
    assert "security" in out.lower() and "no findings" in out.lower()
