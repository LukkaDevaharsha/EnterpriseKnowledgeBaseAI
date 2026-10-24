"""SMTP delivery adapter. Tests replace ``send_verification_code`` directly."""

import smtplib
from email.message import EmailMessage

from flask import current_app


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
    message.set_content(
        f"Your one-time verification code is {code}. It expires in 10 minutes."
    )
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
