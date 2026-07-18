"""Application configuration, loaded from environment / .env file."""

from functools import lru_cache
from pathlib import Path
import os
from dataclasses import dataclass

from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class AttachmentMeta:
    key: str
    label: str
    path: str

def parse_attachments(raw: str) -> list[AttachmentMeta]:
    """`key:label:path` or `key:path` entries, comma-separated. Tolerant of spaces; skips blanks."""
    out: list[AttachmentMeta] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = [p.strip() for p in entry.split(":")]
        if len(parts) == 2 and all(parts):
            key, path = parts
            label = key.replace("_", " ").title()
            out.append(AttachmentMeta(key, label, path))
        elif len(parts) >= 3 and all(parts[:2]):
            key = parts[0]
            label = parts[1]
            path = ":".join(parts[2:]).strip()
            if path:
                out.append(AttachmentMeta(key, label, path))
    return out

def resolve_attachments(keys: list[str], metas: list[AttachmentMeta]) -> list[str]:
    """Map selected keys -> file paths. Raise on unknown key or missing file (never
    silently drop an attachment the user opted into)."""
    by_key = {m.key: m for m in metas}
    paths: list[str] = []
    for k in keys:
        if k not in by_key:
            raise KeyError(f"Unknown attachment key: {k}")
        p = by_key[k].path
        if not os.path.isfile(p):
            raise FileNotFoundError(f"Attachment file missing for '{k}': {p}")
        paths.append(p)
    return paths

# Single source of truth: the repo-root .env, resolved by absolute path so it loads the
# same file whether the process starts from the repo root or from api/. In Docker the vars
# come from the environment (compose env_file), so this path simply won't exist — harmless.
_REPO_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    # extra="allow": dynamically-named vars (GMAIL_<NAME>_REFRESH_TOKEN) from the
    # .env file land in model_extra so load_accounts can find them.
    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT_ENV), env_file_encoding="utf-8", extra="allow"
    )

    # --- Storage ---
    data_dir: str = "./data"

    # --- User locale ---
    timezone: str = "Asia/Kolkata"  # IANA tz; used for reminder time parsing & cron triggers

    # --- LLM provider (swappable: gemini | anthropic | groq) ---
    model_provider: str = "gemini"
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    groq_api_key: str = ""
    # Per-role models: cheap one for classification, stronger for drafting/chat.
    classify_model: str = "gemini-flash-latest"
    draft_model: str = "gemini-flash-latest"
    chat_model: str = "gemini-flash-latest"

    # --- Telegram ---
    telegram_bot_token: str = ""
    telegram_chat_id: int = 0
    telegram_enabled: bool = True   # TELEGRAM_ENABLED — off when Telegram is unreachable (e.g. ISP block)

    # --- Gmail ---
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    # Comma-separated account names; refresh tokens come from GMAIL_<NAME>_REFRESH_TOKEN.
    gmail_accounts: str = ""

    # --- Triage ---
    gmail_triage_cron: str = "0 */6 * * *"  # every 6 hours by default
    gmail_triage_lookback_hours: int = 48  # only consider unread mail from the last N hours
    key_senders: str = ""  # comma-separated domains/addresses always critical
    excluded_topics: str = ""  # comma-separated topics always skipped
    max_emails_per_run: int = 50

    # --- API ---
    api_token: str = ""
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    dashboard_url: str = "http://localhost:3000"

    # --- Drafts / Outreach ---
    user_name: str = ""
    user_signature: str = ""
    outreach_account: str = ""        # empty -> first of account_names
    attachments: str = ""
    soul_file: str = ""
    # "Sent with rotom" footer. URL is the hard prerequisite (empty -> no footer
    # ever). `enabled` is the dashboard switch's default + the fallback for
    # programmatic sends that omit the per-request flag.
    email_footer_enabled: bool = True   # EMAIL_FOOTER_ENABLED
    email_footer_url: str = ""          # EMAIL_FOOTER_URL

    # --- Coding agent (GitHub F2) ---
    claude_code_oauth_token: str = ""     # CLAUDE_CODE_OAUTH_TOKEN
    coding_agent_repos: str = ""          # comma list of allow-listed owner/repo
    coding_agent_max_turns: int = 30
    coding_agent_max_budget_usd: float = 5.0
    coding_agent_timeout: int = 1200      # seconds; docker run wall-clock
    coding_agent_max_fix_rounds: int = 2
    coding_agent_test_cmd: str = ""       # optional; coder is told to make it pass
    coding_agent_worktree_dir: str = "data/coding"
    coding_agent_sandbox_image: str = "rotom-coding:latest"
    coding_agent_container_mem: str = "4g"
    coding_agent_container_cpus: str = "2"
    # docker --network mode for the coder container ("" = host default/bridge).
    # Set to "none" to fully isolate egress where the sandbox image pre-bakes deps;
    # this is the only control that contains a leaked CLAUDE_CODE_OAUTH_TOKEN.
    coding_agent_sandbox_network: str = ""

    # --- Observability ---
    observability_backends: str = "sqlite"
    # Local log retention — entries older than this are pruned at startup.
    # Increase or set to 0 to keep more history. The pluggable sink seam is
    # the right place to add external shipping (e.g. Datadog, Loki) later.
    log_retention_days: int = 14

    @property
    def db_path(self) -> str:
        return f"{self.data_dir}/rotom.db"

    @property
    def checkpoint_db_path(self) -> str:
        return f"{self.data_dir}/checkpoints.db"

    @property
    def observability_db_path(self) -> str:
        return f"{self.data_dir}/observability.db"

    @property
    def account_names(self) -> list[str]:
        return [a.strip() for a in self.gmail_accounts.split(",") if a.strip()]

    @property
    def key_sender_list(self) -> list[str]:
        return [s.strip().lower() for s in self.key_senders.split(",") if s.strip()]

    @property
    def excluded_topic_list(self) -> list[str]:
        return [t.strip() for t in self.excluded_topics.split(",") if t.strip()]

    @property
    def coding_agent_repo_list(self) -> list[str]:
        return [r.strip() for r in self.coding_agent_repos.split(",") if r.strip()]

    @property
    def attachment_list(self) -> list[AttachmentMeta]:
        return parse_attachments(self.attachments)

    @property
    def outreach_account_name(self) -> str:
        return self.outreach_account or (self.account_names[0] if self.account_names else "")


# Placeholder shipped in .env.example — treated as "unset" so a copied-but-unedited
# env can't bring the API up with effectively no auth.
_API_TOKEN_PLACEHOLDER = "change-me-long-random-string"


def validate_required_settings(settings: Settings) -> None:
    """Fail fast on a misconfigured deploy. Call once at startup before serving.

    A blank (or still-placeholder) API_TOKEN would make the bearer check accept
    `Bearer ` with an empty secret — i.e. an unauthenticated API. Refuse to start.
    """
    if not settings.api_token or settings.api_token == _API_TOKEN_PLACEHOLDER:
        raise ValueError(
            "API_TOKEN is empty or still the .env.example placeholder. "
            "Set a long random API_TOKEN before starting rotom (the API is "
            "unauthenticated otherwise)."
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
