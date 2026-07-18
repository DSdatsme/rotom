from app.store.db import CodingRun, CodingStatus, get_session


def test_coding_run_roundtrip(session_db):
    with get_session() as s:
        run = CodingRun(
            issue_url="https://github.com/DSdatsme/rotom/issues/12",
            repo="DSdatsme/rotom",
            issue_number=12,
            status=CodingStatus.RUNNING,
        )
        s.add(run)
        s.flush()
        rid = run.id
    with get_session() as s:
        got = s.get(CodingRun, rid)
        assert got.repo == "DSdatsme/rotom"
        assert got.issue_number == 12
        assert got.status == CodingStatus.RUNNING
        assert got.created_at is not None


def test_coding_status_values():
    assert CodingStatus.BLOCKED == "blocked"
    assert set(CodingStatus) >= {
        CodingStatus.RUNNING, CodingStatus.REVIEW, CodingStatus.BLOCKED,
        CodingStatus.DONE, CodingStatus.FAILED,
    }
