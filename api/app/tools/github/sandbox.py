"""The only place Claude executes: builds + runs an ephemeral docker container.

Command construction is split into pure builders (unit-tested) from the actual
`docker run` invocation (manually verified). Inngest orchestrates; Docker isolates.
"""

import asyncio
import json
import logging

logger = logging.getLogger(__name__)


def build_claude_argv(prompt: str, *, allowed_tools: str, max_turns: int,
                      max_budget_usd: float, resume: str | None) -> list[str]:
    """The `claude` headless CLI argv (runs inside the container)."""
    argv = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--allowedTools", allowed_tools,
        "--permission-mode", "acceptEdits",
        "--max-turns", str(max_turns),
        "--max-budget-usd", str(max_budget_usd),
    ]
    if resume:
        argv += ["--resume", resume]
    return argv


def build_docker_command(*, image: str, worktree: str, session_dir: str, token: str,
                         read_only: bool, mem: str, cpus: str,
                         network: str = "") -> list[str]:
    """The `docker run --rm` prefix: mounts, caps, env, workdir, image.

    `token` is passed as an env var into the container; we set it via `-e NAME`
    and supply the value through the process environment at run time (so it never
    appears in argv/logs). The worktree mounts at /work; reviewers mount it :ro.

    `network` controls egress: when non-empty it becomes `--network <network>`
    (e.g. "none" to fully isolate). Reviewers run with no network at all, and the
    coder's network mode is operator-configurable — this is the only barrier that
    actually contains a leaked OAuth token, since the token is necessarily readable
    from the container environment (e.g. /proc/1/environ) by issue-driven Bash.
    `no-new-privileges` blocks setuid escalation inside the (untrusted) container.
    """
    work_mount = f"{worktree}:/work" + (":ro" if read_only else "")
    cmd = [
        "docker", "run", "--rm",
        "--user", "agent",
        "--security-opt", "no-new-privileges",
    ]
    if network:
        cmd += ["--network", network]
    cmd += [
        "-v", work_mount,
        "-v", f"{session_dir}:/home/agent/.claude",
        "-w", "/work",
        "--memory", mem,
        "--cpus", cpus,
        "--pids-limit", "512",
        "-e", "CLAUDE_CODE_OAUTH_TOKEN",
        "-e", "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1",
        image,
    ]
    return cmd


def parse_claude_json(stdout: str, *, returncode: int, stderr: str = "") -> dict:
    """Parse `claude --output-format json` stdout. Raises RuntimeError on failure.

    On a non-zero exit the useful detail is on stderr, so surface that (falling
    back to stdout when stderr is empty).
    """
    if returncode != 0:
        detail = (stderr or stdout)[:500]
        raise RuntimeError(f"claude exited {returncode}: {detail}")
    try:
        obj = json.loads(stdout)
    except (ValueError, TypeError) as e:
        raise RuntimeError(f"claude produced non-JSON output: {stdout[:500]}") from e
    if obj.get("is_error"):
        raise RuntimeError(f"claude reported error: {obj.get('result', '')[:500]}")
    return obj


async def run_claude_in_container(prompt: str, *, worktree: str, session_dir: str,
                                  settings, read_only: bool = False,
                                  resume: str | None = None) -> dict:
    """Run one Claude invocation inside an ephemeral container; return parsed JSON.

    The only place untrusted code executes. Times out per CODING_AGENT_TIMEOUT.
    """
    import os

    allowed = "Read,Bash(git diff*)" if read_only else "Read,Edit,Bash"
    # Reviewers only read a diff — they never need network, so isolate them fully.
    # The coder's network is operator-configurable (default: host default).
    network = "none" if read_only else settings.coding_agent_sandbox_network
    docker_cmd = build_docker_command(
        image=settings.coding_agent_sandbox_image, worktree=worktree,
        session_dir=session_dir, token=settings.claude_code_oauth_token,
        read_only=read_only, mem=settings.coding_agent_container_mem,
        cpus=settings.coding_agent_container_cpus, network=network,
    )
    claude_argv = build_claude_argv(
        prompt, allowed_tools=allowed, max_turns=settings.coding_agent_max_turns,
        max_budget_usd=settings.coding_agent_max_budget_usd, resume=resume,
    )
    cmd = docker_cmd + claude_argv
    env = {**os.environ, "CLAUDE_CODE_OAUTH_TOKEN": settings.claude_code_oauth_token}
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
    )
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(), timeout=settings.coding_agent_timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"claude container timed out after {settings.coding_agent_timeout}s")
    err_text = err.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        logger.warning("claude container stderr: %s", err_text[:500])
    return parse_claude_json(out.decode("utf-8", errors="replace"),
                             returncode=proc.returncode, stderr=err_text)
