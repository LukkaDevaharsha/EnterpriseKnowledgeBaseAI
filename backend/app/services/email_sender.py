"""SMTP and Resend delivery adapters for verification messages."""

import base64
import html
import json
import socket
import smtplib
from email.message import EmailMessage
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app


GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_TOKEN_URI = "https://oauth2.googleapis.com/token"
DEFAULT_GMAIL_SENDER = "webmanagerepm01@gmail.com"


class EmailDeliveryError(RuntimeError):
    """Delivery failure with diagnostics safe to include in application logs."""

    def __init__(self, category, *, missing_settings=(), smtp_code=None, os_error=None):
        super().__init__(category)
        self.category = category
        self.missing_settings = tuple(missing_settings)
        self.smtp_code = smtp_code
        self.os_error = os_error


def send_verification_code(recipient, code):
    config = current_app.config
    if config.get("EMAIL_PROVIDER", "smtp") == "gmail_api":
        return _send_with_gmail_api(recipient, code, config)
    if config.get("EMAIL_PROVIDER", "smtp") == "resend":
        return _send_with_resend(recipient, code, config)
    return _send_with_smtp(recipient, code, config)


def _message_text(code):
    return f"Your one-time verification code is {code}. It expires in 10 minutes."


def _send_with_smtp(recipient, code, config):
    host = config.get("SMTP_HOST")
    sender = config.get("SMTP_FROM")
    missing = tuple(
        setting for setting, value in (("SMTP_HOST", host), ("SMTP_FROM", sender))
        if not value
    )
    if missing:
        raise EmailDeliveryError("missing_configuration", missing_settings=missing)
    if config.get("SMTP_USERNAME") and not config.get("SMTP_PASSWORD"):
        raise EmailDeliveryError(
            "missing_configuration", missing_settings=("SMTP_PASSWORD",)
        )

    message = EmailMessage()
    message["Subject"] = "Verify your Enterprise Knowledge Base account"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(_message_text(code))
    try:
        with smtplib.SMTP(
            host, config["SMTP_PORT"], timeout=config["SMTP_TIMEOUT_SECONDS"]
        ) as server:
            if config["SMTP_USE_TLS"]:
                server.starttls()
            if config.get("SMTP_USERNAME"):
                server.login(config["SMTP_USERNAME"], config["SMTP_PASSWORD"])
            server.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise EmailDeliveryError(
            "smtp_authentication", smtp_code=exc.smtp_code
        ) from None
    except smtplib.SMTPConnectError as exc:
        raise EmailDeliveryError("smtp_connection", smtp_code=exc.smtp_code) from None
    except smtplib.SMTPResponseException as exc:
        raise EmailDeliveryError("smtp_rejection", smtp_code=exc.smtp_code) from None
    except (smtplib.SMTPServerDisconnected, OSError) as exc:
        raise EmailDeliveryError(
            "network_or_connection", os_error=getattr(exc, "errno", None)
        ) from None
    except smtplib.SMTPException:
        raise EmailDeliveryError("smtp_failure") from None


def _send_with_resend(recipient, code, config):
    api_key = config.get("RESEND_API_KEY")
    sender = config.get("RESEND_FROM_EMAIL")
    missing = tuple(
        setting for setting, value in (
            ("RESEND_API_KEY", api_key), ("RESEND_FROM_EMAIL", sender)
        ) if not isinstance(value, str) or not value.strip()
    )
    if missing:
        raise EmailDeliveryError("missing_configuration", missing_settings=missing)

    payload = json.dumps({
        "from": sender,
        "to": [recipient],
        "subject": "Verify your Enterprise Knowledge Base account",
        "text": _message_text(code),
    }).encode("utf-8")
    request = Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=config.get("RESEND_TIMEOUT_SECONDS", 10)) as response:
            status = getattr(response, "status", 200)
            if not 200 <= status < 300:
                raise EmailDeliveryError("resend_rejection")
            response.read(64 * 1024)
    except HTTPError as exc:
        raise EmailDeliveryError("resend_rejection") from None
    except URLError as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (TimeoutError, socket.timeout)) or "timeout" in type(reason).__name__.lower():
            raise EmailDeliveryError("resend_timeout") from None
        raise EmailDeliveryError("resend_connection") from None
    except (TimeoutError, OSError) as exc:
        if isinstance(exc, TimeoutError) or getattr(exc, "errno", None) in {
            60, 110, 10060,
        }:
            raise EmailDeliveryError("resend_timeout") from None
        raise EmailDeliveryError("resend_connection") from None


def _gmail_dependencies():
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.oauth2.credentials import Credentials
    from google_auth_httplib2 import AuthorizedHttp
    from googleapiclient.discovery import build
    import httplib2

    return Credentials, GoogleAuthRequest, AuthorizedHttp, httplib2, build


def _build_gmail_service(config):
    """Build a Gmail API client with refresh-token OAuth and bounded HTTP calls."""
    Credentials, GoogleAuthRequest, AuthorizedHttp, httplib2, build = _gmail_dependencies()
    timeout = float(config.get("GMAIL_TIMEOUT_SECONDS", 10))

    credentials = Credentials(
        token=None,
        refresh_token=config["GMAIL_REFRESH_TOKEN"],
        token_uri=GMAIL_TOKEN_URI,
        client_id=config["GMAIL_CLIENT_ID"],
        client_secret=config["GMAIL_CLIENT_SECRET"],
        scopes=[GMAIL_SEND_SCOPE],
    )
    if not credentials.valid:
        auth_request = GoogleAuthRequest()
        credentials.refresh(
            lambda url, **kwargs: auth_request(
                url, timeout=timeout, **kwargs
            )
        )
    http = AuthorizedHttp(credentials, http=httplib2.Http(timeout=timeout))
    return build("gmail", "v1", http=http, cache_discovery=False)


def _send_with_gmail_api(recipient, code, config):
    required = (
        "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN",
        "GMAIL_SENDER_EMAIL",
    )
    missing = tuple(
        key for key in required
        if not isinstance(config.get(key), str) or not config[key].strip()
    )
    if missing:
        raise EmailDeliveryError("missing_configuration", missing_settings=missing)

    message = EmailMessage()
    message["Subject"] = "Verify your Enterprise Knowledge Base account"
    message["From"] = config["GMAIL_SENDER_EMAIL"]
    message["To"] = recipient
    text_body = _message_text(code)
    message.set_content(text_body)
    message.add_alternative(
        "<p>Your one-time verification code is <strong>"
        + html.escape(str(code))
        + "</strong>. It expires in 10 minutes.</p>",
        subtype="html",
    )
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")

    try:
        service = _build_gmail_service(config)
        service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
    except Exception as exc:
        if isinstance(exc, EmailDeliveryError):
            raise
        status = getattr(exc, "status_code", None)
        response = getattr(exc, "resp", None)
        if status is None and response is not None:
            status = getattr(response, "status", None)
        if _is_timeout_error(exc):
            raise EmailDeliveryError("gmail_timeout") from None
        if status == 401:
            raise EmailDeliveryError("gmail_authentication") from None
        if status == 429 or (isinstance(status, int) and status >= 500):
            raise EmailDeliveryError("gmail_unavailable") from None
        if isinstance(exc, ImportError):
            raise EmailDeliveryError("gmail_sdk_missing") from None
        raise EmailDeliveryError("gmail_api_failure") from None


def _is_timeout_error(exc):
    current = exc
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (TimeoutError, socket.timeout)) or "timeout" in type(current).__name__.lower():
            return True
        current = current.__cause__ or current.__context__
    return False
