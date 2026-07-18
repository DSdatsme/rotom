"""Inngest client. Dev mode (no signing) unless INNGEST_DEV is unset in production.

pydantic-settings does not export .env values into os.environ, but the inngest SDK
reads INNGEST_DEV itself — so bridge the .env value into the env before constructing
the client. Real environment variables still win (docker/CI).
"""

import os

import inngest

from app.config import get_settings

_settings = get_settings()
_extra = _settings.model_extra or {}
if "INNGEST_DEV" not in os.environ and _extra.get("inngest_dev"):
    os.environ["INNGEST_DEV"] = str(_extra["inngest_dev"])

inngest_client = inngest.Inngest(
    app_id="rotom",
    is_production=os.getenv("INNGEST_DEV") is None,
)
