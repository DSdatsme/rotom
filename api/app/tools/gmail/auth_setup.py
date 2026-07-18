"""One-time OAuth setup per Gmail account.

Run locally (opens a browser for consent):

    uv run python -m app.tools.gmail.auth_setup <account-name>

Prints the GMAIL_<NAME>_REFRESH_TOKEN line to add to your .env.
Requires GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET in the environment or .env.
"""

import sys

from google_auth_oauthlib.flow import InstalledAppFlow

from app.config import get_settings
from app.tools.gmail.client import SCOPES


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m app.tools.gmail.auth_setup <account-name>")
        sys.exit(1)
    account = sys.argv[1]
    settings = get_settings()
    if not settings.gmail_client_id or not settings.gmail_client_secret:
        print("GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET must be set (env or .env)")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": settings.gmail_client_id,
                "client_secret": settings.gmail_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        },
        scopes=SCOPES,
    )
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    env_name = account.upper().replace("-", "_")
    print(f"\nAdd this to your .env:\n\nGMAIL_{env_name}_REFRESH_TOKEN={creds.refresh_token}\n")
    print(f'And ensure "{account}" is listed in GMAIL_ACCOUNTS.')


if __name__ == "__main__":
    main()
