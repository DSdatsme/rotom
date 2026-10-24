from app.config import get_settings


def test_cron_fires_at_local_time():
    from app.workflows.morning_digest import morning_digest
    crons = [t.cron for t in morning_digest._triggers if hasattr(t, "cron")]
    assert crons == [f"TZ={get_settings().timezone} 30 8 * * *"]


def test_failures_are_recorded_once_retries_run_out():
    from app.workflows.morning_digest import morning_digest
    assert morning_digest.on_failure_fn_id is not None


def test_workflow_registered():
    from app.workflows.morning_digest import morning_digest
    from app.workflows.registry import WORKFLOW_FUNCTIONS
    assert morning_digest in WORKFLOW_FUNCTIONS
