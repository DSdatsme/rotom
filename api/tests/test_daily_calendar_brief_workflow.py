def test_workflow_imports_without_inngest_server_or_token():
    from app.workflows.daily_calendar_brief import daily_calendar_brief
    assert daily_calendar_brief is not None


def test_workflow_registered():
    from app.workflows.daily_calendar_brief import daily_calendar_brief
    from app.workflows.registry import WORKFLOW_FUNCTIONS
    assert daily_calendar_brief in WORKFLOW_FUNCTIONS
