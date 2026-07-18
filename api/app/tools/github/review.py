"""Reviewer roster + review-prompt builder + tolerant findings parser.

Reviewers are fresh, read-only Claude sessions over the final diff. Each returns
a JSON object {"findings": [{severity,title,detail}, ...]} which we parse
defensively (LLM output may be wrapped in prose / code fences / be malformed).
"""

import json
import re

REVIEWERS: list[dict] = [
    {
        "name": "reviewer",
        "prompt": (
            "You are a senior engineer reviewing a pull request diff. Find correctness "
            "bugs, missing edge cases, broken tests, and unclear code. Be specific."
        ),
    },
    {
        "name": "security",
        "prompt": (
            "You are a security reviewer. Look for injection, unsafe input handling, "
            "secret leakage, auth/permission gaps, and unsafe subprocess/file usage."
        ),
    },
]

_FINDINGS_SCHEMA_HINT = (
    'Respond ONLY with JSON: {"findings": [{"severity": "high|medium|low|info", '
    '"title": "...", "detail": "..."}]}. Empty list if nothing.'
)


def build_review_prompt(reviewer: dict, diff: str) -> str:
    return f"{reviewer['prompt']}\n\n{_FINDINGS_SCHEMA_HINT}\n\n## Diff\n\n{diff}"


def parse_findings(raw: str) -> list[dict]:
    """Extract the findings list from a model response. Returns [] on any failure."""
    if not raw or not raw.strip():
        return []
    candidates = [raw]
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        candidates.append(m.group(0))
    for c in candidates:
        try:
            obj = json.loads(c)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict) and isinstance(obj.get("findings"), list):
            return [f for f in obj["findings"] if isinstance(f, dict)]
    return []
