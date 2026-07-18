"""Path-layout invariants for the coding-agent workflow.

The Claude session dir MUST live outside the git worktree: the workflow runs
`git add -A` in the worktree, so anything inside it (incl. Claude's session
transcripts under ~/.claude) would be committed and pushed to the PR branch.
"""

from types import SimpleNamespace

from app.workflows import code_issue as W


def _settings(base="data/coding"):
    return SimpleNamespace(coding_agent_worktree_dir=base)


def test_session_dir_is_not_inside_worktree():
    s = _settings()
    wt = W.worktree_path(s, "owner", "repo", 12)
    sd = W.session_dir_path(s, "owner", "repo", 12)
    # The session dir must not be nested under the worktree (so git add -A misses it).
    assert not (sd == wt or sd.startswith(wt.rstrip("/") + "/"))


def test_paths_are_deterministic_per_issue():
    s = _settings()
    assert W.worktree_path(s, "o", "r", 3) == W.worktree_path(s, "o", "r", 3)
    assert W.session_dir_path(s, "o", "r", 3) == W.session_dir_path(s, "o", "r", 3)
    # Different issues get different session dirs.
    assert W.session_dir_path(s, "o", "r", 3) != W.session_dir_path(s, "o", "r", 4)
