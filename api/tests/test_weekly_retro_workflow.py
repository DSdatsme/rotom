def test_workflow_imports_without_inngest_server_or_token():
    from app.workflows.weekly_retro import weekly_retro
    assert weekly_retro is not None


def test_workflow_registered():
    from app.workflows.registry import WORKFLOW_FUNCTIONS
    from app.workflows.weekly_retro import weekly_retro
    assert weekly_retro in WORKFLOW_FUNCTIONS
