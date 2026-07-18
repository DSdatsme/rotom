import app.agent.toolkit as TK


def test_work_on_issue_is_registered():
    assert TK.work_on_issue in TK.ALL_TOOLS


def test_work_on_issue_fires_event_for_allowed_repo(monkeypatch):
    sent = []
    import app.workflows.client as client
    monkeypatch.setattr(client.inngest_client, "send_sync", lambda ev: sent.append(ev))
    monkeypatch.setattr("app.config.get_settings",
                        lambda: _S(coding_agent_repos="DSdatsme/rotom"))
    out = TK.work_on_issue.invoke({"url": "https://github.com/DSdatsme/rotom/issues/12"})
    assert len(sent) == 1
    assert sent[0].name == "workflows/code-issue.requested"
    assert sent[0].data["url"].endswith("/issues/12")
    assert "triggered" in out.lower()


def test_work_on_issue_refuses_disallowed_repo(monkeypatch):
    sent = []
    import app.workflows.client as client
    monkeypatch.setattr(client.inngest_client, "send_sync", lambda ev: sent.append(ev))
    monkeypatch.setattr("app.config.get_settings",
                        lambda: _S(coding_agent_repos="DSdatsme/rotom"))
    out = TK.work_on_issue.invoke({"url": "https://github.com/evil/repo/issues/1"})
    assert sent == []
    assert "not allow" in out.lower() or "not in" in out.lower()


def test_work_on_issue_rejects_bad_url(monkeypatch):
    monkeypatch.setattr("app.config.get_settings",
                        lambda: _S(coding_agent_repos="DSdatsme/rotom"))
    out = TK.work_on_issue.invoke({"url": "https://github.com/DSdatsme/rotom/pull/12"})
    assert "issue url" in out.lower() or "invalid" in out.lower()


def _S(**kw):
    from app.config import Settings
    return Settings(**kw)
