"""All workflow functions, handed to inngest.fast_api.serve()."""

from app.workflows.code_issue import code_issue
from app.workflows.daily_calendar_brief import daily_calendar_brief
from app.workflows.hello import hello
from app.workflows.morning_digest import morning_digest
from app.workflows.weekly_retro import weekly_retro

WORKFLOW_FUNCTIONS = [hello, morning_digest, code_issue, daily_calendar_brief, weekly_retro]
