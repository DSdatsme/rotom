def test_workflow_imports_without_inngest_server_or_token():
    from app.workflows.code_issue import code_issue
    assert code_issue is not None


def test_workflow_registered():
    from app.workflows.registry import WORKFLOW_FUNCTIONS
    from app.workflows.code_issue import code_issue
    assert code_issue in WORKFLOW_FUNCTIONS
