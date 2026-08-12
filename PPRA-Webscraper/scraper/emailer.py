"""Gmail API email sender — CI-safe.

The most common reason a scraper like this "stops working" is Gmail auth.
Two traps, both handled here:

  1. *Interactive auth in CI.* When the stored token is missing or unusable,
     calling ``flow.run_local_server()`` tries to open a browser. On a headless
     GitHub Actions runner that hangs the job. Here the interactive flow only
     runs when explicitly asked for (``--auth`` locally); in CI a bad token
     raises a clear, actionable error instead.

  2. *The 7-day refresh-token expiry.* An OAuth app left in "Testing" publishing
     status issues refresh tokens that Google expires after **7 days**, so email
     quietly dies about a week after setup. The error message below says exactly
     that and how to fix it, and a successful refresh is written back to
     ``token.json`` so it can be copied into the secret.

Heavy Google libraries are imported lazily, so the pure message-building logic
below is unit-testable with only the standard library installed.
"""

from __future__ import annotations

import base64
import os
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from scraper.config import CREDENTIALS_PATH, GMAIL_SCOPES, TOKEN_PATH


# ---------------------------------------------------------------------------
# Message construction — pure, no Google dependency
# ---------------------------------------------------------------------------

def build_message(sender: str, recipient: str, subject: str, html_body: str,
                  files: list[str]) -> dict:
    """A base64url-encoded Gmail message with an HTML body and file attachments.
    Missing attachment paths are skipped (with a note) rather than opening every
    path unconditionally and dying on the first miss."""
    msg = MIMEMultipart()
    msg["to"] = recipient
    msg["from"] = sender
    msg["subject"] = subject
    msg.attach(MIMEText(html_body, "html"))

    for path in files:
        if not path or not os.path.exists(path):
            print(f"  attachment not found, skipping: {path}")
            continue
        with open(path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition",
                        f'attachment; filename="{os.path.basename(path)}"')
        msg.attach(part)

    return {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}


# ---------------------------------------------------------------------------
# Authentication — CI-safe
# ---------------------------------------------------------------------------

def _auth_help(reason: str) -> str:
    return (
        f"Gmail authentication failed: {reason}.\n"
        "  • Most often this is the OAuth 'Testing' 7-day refresh-token expiry: an\n"
        "    app in Testing status has refresh tokens that Google revokes after 7\n"
        "    days, so email stops ~a week after setup.\n"
        "  Fixes:\n"
        "    1. Regenerate the token locally:  python -m scraper.main --auth\n"
        "       then base64 scraper/token.json into the TOKEN_JSON secret.\n"
        "    2. To stop the weekly expiry, set the app's publishing status to\n"
        "       'In production' (or use a service account with domain delegation)."
    )


def _save_token(creds) -> None:
    with open(TOKEN_PATH, "w") as f:
        f.write(creds.to_json())


def get_credentials(allow_interactive: bool = False):
    """Return valid Gmail credentials, or raise a clear error. Never opens a
    browser unless `allow_interactive` is True (a local `--auth` run)."""
    from google.oauth2.credentials import Credentials

    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, GMAIL_SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        try:
            creds.refresh(Request())
            _save_token(creds)
            print("Gmail token refreshed and written to token.json.")
            return creds
        except Exception as exc:                     # RefreshError, transport errors
            raise RuntimeError(_auth_help(f"token refresh failed ({exc})")) from exc

    if allow_interactive:
        return authenticate_interactive()

    raise RuntimeError(_auth_help("no valid token and interactive auth is disabled in CI"))


def authenticate_interactive():
    """Run the local browser OAuth flow to (re)create token.json. LOCAL ONLY."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not os.path.exists(CREDENTIALS_PATH):
        raise RuntimeError(
            f"{CREDENTIALS_PATH} not found — download the OAuth 2.0 Desktop-app "
            "credentials from Google Cloud Console and save them there first."
        )
    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, GMAIL_SCOPES)
    creds = flow.run_local_server(port=0)
    _save_token(creds)
    print(f"Wrote {TOKEN_PATH}. Base64-encode it into the TOKEN_JSON secret for CI.")
    return creds


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def send_report(sender: str, recipient: str, subject: str, html_body: str,
                excel_path: str, pdf_files: list[str], allow_interactive: bool = False) -> None:
    """Send the report email. Raises with actionable guidance on auth failure so
    the CI job fails loudly (and legibly) instead of hanging."""
    from googleapiclient.discovery import build

    service = build("gmail", "v1", credentials=get_credentials(allow_interactive))
    files = [excel_path] + list(pdf_files)
    message = build_message(sender, recipient, subject, html_body, files)
    service.users().messages().send(userId="me", body=message).execute()
    print(f"Email sent to {recipient} with {sum(os.path.exists(f) for f in files)} attachment(s).")
