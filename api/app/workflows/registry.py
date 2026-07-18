"""All workflow functions, handed to inngest.fast_api.serve()."""

from app.workflows.code_issue import code_issue
from app.workflows.hello import hello
from app.workflows.morning_digest import morning_digest

WORKFLOW_FUNCTIONS = [hello, morning_digest, code_issue]
