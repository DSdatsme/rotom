import json
import pytest
from app.tools.github import sandbox as S


def test_build_claude_argv_basic():
    argv = S.build_claude_argv("do the thing", allowed_tools="Read,Edit,Bash",
                               max_turns=30, max_budget_usd=5.0, resume=None)
    assert argv[0] == "claude"
    assert "-p" in argv and "do the thing" in argv
    assert "--output-format" in argv and "json" in argv
    assert "--allowedTools" in argv and "Read,Edit,Bash" in argv
    assert "--max-turns" in argv and "30" in argv
    assert "--resume" not in argv


def test_build_claude_argv_resume():
    argv = S.build_claude_argv("fix ci", allowed_tools="Read,Edit,Bash",
                               max_turns=30, max_budget_usd=5.0, resume="sess-1")
    assert "--resume" in argv and "sess-1" in argv


def test_build_docker_command_mounts_and_caps():
    cmd = S.build_docker_command(
        image="rotom-coding:latest", worktree="/data/coding/o/r/12",
        session_dir="/data/coding/o/r/12/claude-home", token="tok",
        read_only=False, mem="4g", cpus="2",
    )
    assert cmd[:3] == ["docker", "run", "--rm"]
    joined = " ".join(cmd)
    assert "-v /data/coding/o/r/12:/work" in joined
    assert "/work" in cmd
    assert "-v /data/coding/o/r/12/claude-home:/home/agent/.claude" in joined
    assert "--memory" in cmd and "4g" in cmd
    assert "--cpus" in cmd and "2" in cmd
    assert "--pids-limit" in cmd
    assert "rotom-coding:latest" in cmd
    assert "CLAUDE_CODE_OAUTH_TOKEN" in joined


def test_build_docker_command_readonly_mount():
    cmd = S.build_docker_command(
        image="img", worktree="/w", session_dir="/w/h", token="t",
        read_only=True, mem="4g", cpus="2",
    )
    assert "-v /w:/work:ro" in " ".join(cmd)


def test_parse_claude_json_extracts_session_and_result():
    raw = json.dumps({"session_id": "abc", "result": "done", "is_error": False})
    out = S.parse_claude_json(raw, returncode=0)
    assert out["session_id"] == "abc"
    assert out["result"] == "done"


def test_parse_claude_json_nonzero_raises():
    with pytest.raises(RuntimeError):
        S.parse_claude_json("partial", returncode=1)


def test_parse_claude_json_malformed_raises():
    with pytest.raises(RuntimeError):
        S.parse_claude_json("not json", returncode=0)


@pytest.mark.asyncio
async def test_run_cmd_returns_stdout(tmp_path):
    from app.tools.github import runner
    out = await runner.run_cmd(["echo", "hello"])
    assert out.strip() == "hello"


@pytest.mark.asyncio
async def test_run_cmd_raises_on_nonzero():
    from app.tools.github import runner
    with pytest.raises(RuntimeError):
        await runner.run_cmd(["false"])


def test_parse_claude_json_nonzero_surfaces_stderr():
    with pytest.raises(RuntimeError, match="boom on stderr"):
        S.parse_claude_json("", returncode=1, stderr="boom on stderr")


def test_build_docker_command_network_flag_emitted_when_set():
    cmd = S.build_docker_command(
        image="img", worktree="/w", session_dir="/s", token="t",
        read_only=True, mem="4g", cpus="2", network="none",
    )
    assert "--network none" in " ".join(cmd)


def test_build_docker_command_no_network_flag_when_blank():
    cmd = S.build_docker_command(
        image="img", worktree="/w", session_dir="/s", token="t",
        read_only=False, mem="4g", cpus="2", network="",
    )
    assert "--network" not in cmd


def test_build_docker_command_drops_new_privileges():
    cmd = S.build_docker_command(
        image="img", worktree="/w", session_dir="/s", token="t",
        read_only=False, mem="4g", cpus="2",
    )
    assert "no-new-privileges" in " ".join(cmd)
