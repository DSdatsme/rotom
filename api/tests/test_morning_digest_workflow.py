def test_workflow_imports_without_inngest_server_or_token():
    from app.workflows.morning_digest import morning_digest
    assert morning_digest is not None


def test_workflow_registered():
    from app.workflows.morning_digest import morning_digest
    from app.workflows.registry import WORKFLOW_FUNCTIONS
    assert morning_digest in WORKFLOW_FUNCTIONS
