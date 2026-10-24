"""Rate-limited registration challenge helpers; plaintext OTPs are never stored."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from flask import current_app


OTP_TTL = timedelta(minutes=10)
OTP_ATTEMPTS = 5
RESEND_DELAY = timedelta(seconds=60)
MAX_RESENDS = 5


def create_code():
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_code(email, code):
    secret = current_app.config["JWT_SECRET_KEY"].encode("utf-8")
    value = f"{email.lower()}:{code}".encode("utf-8")
    return hmac.new(secret, value, hashlib.sha256).hexdigest()


def code_matches(email, code, expected_hash):
    return hmac.compare_digest(hash_code(email, code), expected_hash)


def now_utc():
    return datetime.now(timezone.utc)
