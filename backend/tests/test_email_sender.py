import logging
import smtplib

import pytest

from app.services import email_sender
from app.services.email_sender import EmailDeliveryError, send_verification_code


def test_sender_reports_missing_smtp_configuration_without_connecting(app, monkeypatch):
    app.config.update(SMTP_HOST="", SMTP_FROM="")

    def unexpected_smtp(*args, **kwargs):
        pytest.fail("SMTP must not be contacted when configuration is missing")

    monkeypatch.setattr(email_sender.smtplib, "SMTP", unexpected_smtp)
    with app.app_context(), pytest.raises(EmailDeliveryError) as raised:
        send_verification_code("recipient@example.test", "123456")

    assert raised.value.category == "missing_configuration"
    assert set(raised.value.missing_settings) == {"SMTP_HOST", "SMTP_FROM"}


@pytest.mark.parametrize(
    ("smtp_exception", "expected_category", "expected_code"),
    [
        (smtplib.SMTPAuthenticationError(535, b"provider detail"), "smtp_authentication", 535),
        (smtplib.SMTPConnectError(421, b"provider detail"), "smtp_connection", 421),
    ],
)
def test_sender_classifies_smtp_failures_without_retaining_provider_response(
    app, monkeypatch, smtp_exception, expected_category, expected_code
):
    app.config.update(
        SMTP_HOST="smtp.example.test", SMTP_PORT=587, SMTP_USE_TLS=True,
        SMTP_USERNAME="configured-user", SMTP_PASSWORD="configured-password",
        SMTP_FROM="sender@example.test", SMTP_TIMEOUT_SECONDS=3,
    )

    class FailingSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def starttls(self):
            pass

        def login(self, *_args):
            if isinstance(smtp_exception, smtplib.SMTPAuthenticationError):
                raise smtp_exception

        def send_message(self, _message):
            raise smtp_exception

    monkeypatch.setattr(email_sender.smtplib, "SMTP", FailingSMTP)
    with app.app_context(), pytest.raises(EmailDeliveryError) as raised:
        send_verification_code("recipient@example.test", "123456")

    assert raised.value.category == expected_category
    assert raised.value.smtp_code == expected_code
    assert "provider detail" not in str(raised.value)


def test_registration_logs_safe_email_failure_category_and_returns_503(
    client, monkeypatch, caplog
):
    def fail_delivery(_recipient, _code):
        raise email_sender.EmailDeliveryError(
            "smtp_authentication", smtp_code=535
        )

    monkeypatch.setattr(email_sender, "send_verification_code", fail_delivery)
    caplog.set_level(logging.WARNING, logger="app.routes.auth")
    response = client.post("/api/auth/register", json={
        "name": "SMTP Failure", "email": "smtp-failure@example.test",
        "department": "IT", "password": "StrongPassword123",
    })

    assert response.status_code == 503
    assert response.get_json()["message"] == (
        "Verification email is temporarily unavailable. Try again later."
    )
    assert "category=smtp_authentication" in caplog.text
    assert "smtp_code=535" in caplog.text
    assert "StrongPassword123" not in caplog.text
