import base64
from email import policy
from email.parser import BytesParser
import json
import sys
import types

import pytest

from app.services import email_sender
from app.services.email_sender import (
    DEFAULT_GMAIL_SENDER,
    GMAIL_SEND_SCOPE,
    EmailDeliveryError,
    send_verification_code,
)


def _gmail_config(app, monkeypatch, **overrides):
    values = {
        "EMAIL_PROVIDER": "gmail_api",
        "GMAIL_CLIENT_ID": "client-id-test",
        "GMAIL_CLIENT_SECRET": "client-secret-test",
        "GMAIL_REFRESH_TOKEN": "refresh-token-test",
        "GMAIL_SENDER_EMAIL": DEFAULT_GMAIL_SENDER,
        "GMAIL_TIMEOUT_SECONDS": 7,
    }
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setitem(app.config, key, value)


class FakeSendRequest:
    def __init__(self, result=None, failure=None):
        self.result = result or {"id": "message-id"}
        self.failure = failure

    def execute(self):
        if self.failure:
            raise self.failure
        return self.result


class FakeGmailService:
    def __init__(self, result=None, failure=None):
        self.sent = None
        self.request = FakeSendRequest(result=result, failure=failure)

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, **kwargs):
        self.sent = kwargs
        return self.request


def test_gmail_api_provider_selection_sender_and_mime_encoding(app, monkeypatch):
    service = FakeGmailService()
    _gmail_config(app, monkeypatch)
    monkeypatch.setattr(email_sender, "_build_gmail_service", lambda _config: service)

    with app.app_context():
        send_verification_code("employee@example.test", "654321")

    assert service.sent["userId"] == "me"
    raw = service.sent["body"]["raw"]
    decoded = base64.urlsafe_b64decode(raw.encode("ascii"))
    message = BytesParser(policy=policy.default).parsebytes(decoded)
    assert message["From"] == "webmanagerepm01@gmail.com"
    assert message["To"] == "employee@example.test"
    assert message["Subject"] == "Verify your Enterprise Knowledge Base account"
    assert message.get_content_type() == "multipart/alternative"
    parts = {part.get_content_type(): part.get_content() for part in message.iter_parts()}
    assert "654321" in parts["text/plain"]
    assert "654321" in parts["text/html"]
    assert "expires in 10 minutes" in parts["text/plain"]


def test_gmail_refresh_token_credentials_use_only_send_scope_and_refresh(app, monkeypatch):
    captured = {}

    class FakeCredentials:
        def __init__(self, **kwargs):
            captured["credentials"] = kwargs
            self.valid = False

        def refresh(self, request):
            captured["refresh_result"] = request("https://oauth.example/token", method="POST")
            self.valid = True

    class FakeAuthRequest:
        def __call__(self, url, **kwargs):
            captured["auth_request"] = (url, kwargs)
            return "refreshed"

    class FakeHttpLib2:
        @staticmethod
        def Http(timeout):
            captured["http_timeout"] = timeout
            return "http-transport"

    class FakeAuthorizedHttp:
        def __init__(self, credentials, http):
            captured["authorized_http"] = (credentials, http)

    def fake_build(api, version, **kwargs):
        captured["build"] = (api, version, kwargs)
        return "service"

    monkeypatch.setattr(
        email_sender,
        "_gmail_dependencies",
        lambda: (FakeCredentials, FakeAuthRequest, FakeAuthorizedHttp, FakeHttpLib2, fake_build),
    )
    _gmail_config(app, monkeypatch)

    with app.app_context():
        result = email_sender._build_gmail_service(app.config)

    assert result == "service"
    assert captured["credentials"] == {
        "token": None,
        "refresh_token": "refresh-token-test",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "client-id-test",
        "client_secret": "client-secret-test",
        "scopes": ["https://www.googleapis.com/auth/gmail.send"],
    }
    assert captured["credentials"]["scopes"] == [GMAIL_SEND_SCOPE]
    assert captured["refresh_result"] == "refreshed"
    assert captured["auth_request"] == (
        "https://oauth.example/token", {"method": "POST", "timeout": 7.0}
    )
    assert captured["http_timeout"] == 7.0
    assert captured["build"][0:2] == ("gmail", "v1")
    assert captured["build"][2]["cache_discovery"] is False


def test_gmail_missing_credentials_are_reported_without_client_creation(app, monkeypatch):
    _gmail_config(
        app, monkeypatch, GMAIL_CLIENT_ID="", GMAIL_CLIENT_SECRET="",
        GMAIL_REFRESH_TOKEN="", GMAIL_SENDER_EMAIL="",
    )
    monkeypatch.setattr(
        email_sender, "_build_gmail_service",
        lambda _config: pytest.fail("Gmail client must not be built"),
    )
    with app.app_context(), pytest.raises(EmailDeliveryError) as raised:
        send_verification_code("employee@example.test", "654321")
    assert raised.value.category == "missing_configuration"
    assert set(raised.value.missing_settings) == {
        "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN",
        "GMAIL_SENDER_EMAIL",
    }


@pytest.mark.parametrize(
    "failure, category",
    [
        (TimeoutError("private timeout"), "gmail_timeout"),
        (type("ApiFailure", (Exception,), {"resp": type("Response", (), {"status": 500})()})(), "gmail_unavailable"),
        (type("ApiFailure", (Exception,), {"resp": type("Response", (), {"status": 400})()})(), "gmail_api_failure"),
    ],
)
def test_gmail_api_failures_are_safe(app, monkeypatch, failure, category):
    _gmail_config(app, monkeypatch)
    service = FakeGmailService(failure=failure)
    monkeypatch.setattr(email_sender, "_build_gmail_service", lambda _config: service)
    with app.app_context(), pytest.raises(EmailDeliveryError) as raised:
        send_verification_code("employee@example.test", "654321")
    assert raised.value.category == category
    assert "private" not in str(raised.value)


def test_local_oauth_helper_requests_only_sender_scope_and_saves_refresh_token(
    monkeypatch, tmp_path, capsys
):
    from tools import authorize_gmail_sender

    captured = {}

    class FakeCredentials:
        refresh_token = "refresh-token-never-print"

    class FakeFlow:
        @classmethod
        def from_client_config(cls, client_config, scopes):
            captured["client_config"] = client_config
            captured["scopes"] = scopes
            return cls()

        def run_local_server(self, **kwargs):
            captured["flow_options"] = kwargs
            return FakeCredentials()

    package = types.ModuleType("google_auth_oauthlib")
    package.__path__ = []
    flow_module = types.ModuleType("google_auth_oauthlib.flow")
    flow_module.InstalledAppFlow = FakeFlow
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib", package)
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib.flow", flow_module)
    monkeypatch.setattr("builtins.input", lambda _prompt: "client-id-never-print")
    monkeypatch.setattr(authorize_gmail_sender.getpass, "getpass", lambda _prompt: "client-secret-never-print")
    monkeypatch.setattr(authorize_gmail_sender, "TOKEN_PATH", tmp_path / ".secrets" / "token.json")

    assert authorize_gmail_sender.main() == 0
    saved = json.loads(authorize_gmail_sender.TOKEN_PATH.read_text(encoding="utf-8"))
    output = capsys.readouterr().out

    assert captured["scopes"] == ["https://www.googleapis.com/auth/gmail.send"]
    assert captured["flow_options"]["access_type"] == "offline"
    assert "consent" in captured["flow_options"]["prompt"]
    assert captured["flow_options"]["login_hint"] == "webmanagerepm01@gmail.com"
    assert saved == {
        "sender_email": "webmanagerepm01@gmail.com",
        "scope": "https://www.googleapis.com/auth/gmail.send",
        "refresh_token": "refresh-token-never-print",
    }
    assert "refresh-token-never-print" not in output
    assert "client-secret-never-print" not in output
