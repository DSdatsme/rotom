from dataclasses import dataclass, field

@dataclass(frozen=True)
class RunResult:
    status: str
    summary: str = ""
    error: str = ""


@dataclass(frozen=True)
class RunStart:
    """Transport-agnostic start payload for a run (keeps the sink Protocol clean).

    `parent_run_id` is the enclosing run captured by `record_run` for automatic
    parent/child nesting; `external_*` link a run to an external engine (Inngest).
    """
    kind: str
    source: str = "system"
    external_id: str | None = None
    external_url: str | None = None
    parent_run_id: str | None = None
    trace_id: str | None = None
