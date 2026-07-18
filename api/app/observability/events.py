from dataclasses import dataclass, field
from datetime import datetime

@dataclass(frozen=True)
class UsageEvent:
    provider: str
    model: str
    role: str
    input_tokens: int
    output_tokens: int
    run_id: str | None
    ts: datetime
    # Feature B: per-call LLM latency in milliseconds (None when not measured)
    latency_ms: int | None = None

@dataclass(frozen=True)
class RunResult:
    status: str
    summary: str = ""
    error: str = ""
    logs: str = ""


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
