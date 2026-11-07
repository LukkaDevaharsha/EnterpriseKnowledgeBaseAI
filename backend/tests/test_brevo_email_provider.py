import json
from urllib.error import HTTPError

import pytest

from app.services import email_sender
from app.services.email_sender import EmailDeliveryError, send_verification_code


class FakeResponse:
    status = 201

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size=-1):
        return b'{"messageId":"test-id"}'


def configure_brevo(app, monkeypatch, **overrides):
    values = {
        "EMAIL_PROVIDER": "brevo", "BREVO_API_KEY": "private-test-key",
        "BREVO_SENDER_EMAIL": "accounts@example.test",
        "BREVO_SENDER_NAME": "Enterprise Knowledge Base AI",
        "BREVO_TIMEOUT_SECONDS": 4,
        "GMAIL_CLIENT_ID": "", "GMAIL_CLIENT_SECRET": "",
        "GMAIL_REFRESH_TOKEN": "", "GMAIL_SENDER_EMAIL": "",
    }
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setitem(app.config, key, value)


def test_brevo_posts_responsive_html_and_plain_text_with_bounded_timeout(app, monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["headers"] = request.headers
        seen["payload"] = json.loads(request.data)
        seen["timeout"] = timeout
        return FakeResponse()

    configure_brevo(app, monkeypatch)
    monkeypatch.setattr(email_sender, "urlopen", fake_urlopen)
    with app.app_context():
        result = send_verification_code("person@example.test", "123456")

    assert result == {"status": "sent", "provider": "brevo"}
    assert seen["url"] == "https://api.brevo.com/v3/smtp/email"
    assert seen["headers"]["Api-key"] == "private-test-key"
    assert seen["headers"]["Content-type"] == "application/json"
    assert seen["headers"]["Accept"] == "application/json"
    assert seen["timeout"] == 4
    assert seen["payload"]["sender"] == {
        "email": "accounts@example.test", "name": "Enterprise Knowledge Base AI",
    }
    assert seen["payload"]["to"] == [{"email": "person@example.test"}]
    assert "123456" in seen["payload"]["textContent"]
    assert "123456" in seen["payload"]["htmlContent"]
    assert "10 minutes" in seen["payload"]["textContent"]


@pytest.mark.parametrize(
    ("failure", "category"),
    [
        (HTTPError("url", 400, "private request detail", {}, None), "brevo_bad_request"),
        (HTTPError("url", 401, "private credential detail", {}, None), "brevo_authentication"),
        (HTTPError("url", 403, "private credential detail", {}, None), "brevo_forbidden"),
        (HTTPError("url", 429, "private response", {}, None), "brevo_rate_limited"),
        (HTTPError("url", 500, "private response", {}, None), "brevo_unavailable"),
        (TimeoutError("private timeout detail"), "brevo_timeout"),
        (OSError("private network detail"), "brevo_connection"),
    ],
)
def test_brevo_provider_failures_are_categorized_without_provider_details(
    app, monkeypatch, failure, category
):
    configure_brevo(app, monkeypatch)
    monkeypatch.setattr(
        email_sender, "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(failure),
    )
    with app.app_context(), pytest.raises(EmailDeliveryError) as raised:
        send_verification_code("person@example.test", "123456")
    assert raised.value.category == category
    assert "private" not in str(raised.value)


def test_brevo_missing_configuration_does_not_make_request(app, monkeypatch):
    configure_brevo(app, monkeypatch, BREVO_API_KEY="", BREVO_SENDER_EMAIL="")
    monkeypatch.setattr(
        email_sender, "urlopen", lambda *_a, **_k: pytest.fail("unexpected request")
    )
    with app.app_context(), pytest.raises(EmailDeliveryError) as raised:
        send_verification_code("person@example.test", "123456")
    assert raised.value.category == "missing_configuration"
    assert set(raised.value.missing_settings) == {"BREVO_API_KEY", "BREVO_SENDER_EMAIL"}


def test_brevo_registration_otp_uses_selected_provider_without_gmail_credentials(
    client, app, monkeypatch
):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["payload"] = json.loads(request.data)
        return FakeResponse()

    configure_brevo(app, monkeypatch)
    monkeypatch.setattr(email_sender, "urlopen", fake_urlopen)
    monkeypatch.setattr(email_sender, "send_verification_code", send_verification_code)
    response = client.post("/api/auth/register", json={
        "name": "Brevo User", "email": "brevo-user@example.test",
        "department": "Research", "password": "StrongPassword123",
    })
    assert response.status_code == 202
    assert "code" not in response.get_json()
    assert "verification code" in seen["payload"]["textContent"]
    assert seen["payload"]["to"] == [{"email": "brevo-user@example.test"}]


def test_brevo_selected_from_environment_without_gmail_settings(monkeypatch, tmp_path):
    from app import create_app

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET_KEY", "brevo-config-test-secret")
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", str(tmp_path / "documents"))
    monkeypatch.setenv("EMAIL_PROVIDER", "brevo")
    monkeypatch.setenv("BREVO_API_KEY", "test-key")
    monkeypatch.setenv("BREVO_SENDER_EMAIL", "accounts@example.test")
    monkeypatch.delenv("GMAIL_CLIENT_ID", raising=False)
    monkeypatch.delenv("GMAIL_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GMAIL_REFRESH_TOKEN", raising=False)

    app = create_app({"TESTING": True})
    assert app.config["EMAIL_PROVIDER"] == "brevo"
    assert app.config["BREVO_API_KEY"] == "test-key"
    assert app.config["GMAIL_CLIENT_ID"] == ""
