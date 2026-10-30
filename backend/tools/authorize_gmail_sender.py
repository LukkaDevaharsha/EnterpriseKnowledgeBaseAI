"""Locally authorize the dedicated Gmail sender and save only its refresh token."""

import getpass
import json
from pathlib import Path
import sys


SENDER_EMAIL = "webmanagerepm01@gmail.com"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
TOKEN_PATH = Path(__file__).resolve().parents[1] / ".secrets" / "gmail_refresh_token.json"


def main():
    client_id = input("OAuth Client ID: ").strip()
    client_secret = getpass.getpass("OAuth Client Secret: ").strip()
    if not client_id or not client_secret:
        print("Client ID and Client Secret are required.", file=sys.stderr)
        return 2

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = InstalledAppFlow.from_client_config(
            {
                "installed": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            },
            scopes=[GMAIL_SEND_SCOPE],
        )
        credentials = flow.run_local_server(
            host="localhost",
            port=0,
            access_type="offline",
            prompt="consent select_account",
            login_hint=SENDER_EMAIL,
        )
    except Exception:
        print(
            "Gmail authorization failed. Check OAuth setup and try again.",
            file=sys.stderr,
        )
        return 1

    if not credentials.refresh_token:
        print(
            "Google did not return a refresh token. Revoke the app grant and retry consent.",
            file=sys.stderr,
        )
        return 1

    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(
        json.dumps({
            "sender_email": SENDER_EMAIL,
            "scope": GMAIL_SEND_SCOPE,
            "refresh_token": credentials.refresh_token,
        }, indent=2),
        encoding="utf-8",
    )
    try:
        TOKEN_PATH.chmod(0o600)
    except OSError:
        pass
    print(f"Refresh token saved locally to: {TOKEN_PATH}")
    print("Copy only the refresh_token value into Render's GMAIL_REFRESH_TOKEN secret.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
