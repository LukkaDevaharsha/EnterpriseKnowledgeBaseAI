from datetime import datetime, timedelta, timezone

from app import db
from app.models import RegistrationChallenge


def start_registration(client, app, email="otp@example.com"):
    response = client.post("/api/auth/register", json={
        "name": "OTP Employee", "email": email,
        "department": "Research", "password": "StrongPassword123",
        "employee_id": "ATTACKER-CHOSEN", "role": "ADMIN",
    })
    return response, app.extensions["test_verification_outbox"].get(email)


def test_otp_verification_creates_generated_employee_and_never_returns_code(client, app):
    response, code = start_registration(client, app)
    assert response.status_code == 202
    assert "code" not in response.get_json()
    with app.app_context():
        challenge = RegistrationChallenge.query.filter_by(email="otp@example.com").one()
        assert challenge.code_hash != code
    verified = client.post("/api/auth/verify", json={"email": "otp@example.com", "code": code})
    assert verified.status_code == 201
    user = verified.get_json()["user"]
    assert user["employee_id"].startswith("EMP")
    assert user["role"] == "EMPLOYEE"
    assert user["is_verified"] is True


def test_unverified_account_cannot_login_and_duplicate_pending_email_is_rejected(client):
    client.post("/api/auth/register", json={
        "name": "Pending", "email": "pending@example.com",
        "department": "Ops", "password": "StrongPassword123",
    })
    assert client.post("/api/auth/login", json={
        "identifier": "pending@example.com", "password": "StrongPassword123",
    }).status_code == 401
    duplicate = client.post("/api/auth/register", json={
        "name": "Pending", "email": "pending@example.com",
        "department": "Ops", "password": "StrongPassword123",
    })
    assert duplicate.status_code == 409


def test_wrong_code_attempt_limit_removes_pending_challenge(client, app):
    start_registration(client, app, "wrong@example.com")
    for _ in range(4):
        response = client.post("/api/auth/verify", json={"email": "wrong@example.com", "code": "000000"})
        assert response.status_code == 400
    response = client.post("/api/auth/verify", json={"email": "wrong@example.com", "code": "000000"})
    assert response.status_code == 429
    with app.app_context():
        assert RegistrationChallenge.query.filter_by(email="wrong@example.com").count() == 0


def test_expired_code_rejected(client, app):
    start_registration(client, app, "expired@example.com")
    with app.app_context():
        challenge = RegistrationChallenge.query.filter_by(email="expired@example.com").one()
        challenge.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.session.commit()
    code = app.extensions["test_verification_outbox"]["expired@example.com"]
    response = client.post("/api/auth/verify", json={"email": "expired@example.com", "code": code})
    assert response.status_code == 400


def test_resend_wait_and_limit_are_enforced(client, app):
    from app.services.registration import MAX_RESENDS

    start_registration(client, app, "resend@example.com")
    payload = {"email": "resend@example.com"}
    assert client.post("/api/auth/resend-verification", json=payload).status_code == 429
    for _ in range(MAX_RESENDS):
        with app.app_context():
            challenge = RegistrationChallenge.query.filter_by(email="resend@example.com").one()
            challenge.last_sent_at = datetime.now(timezone.utc) - timedelta(minutes=2)
            db.session.commit()
        response = client.post("/api/auth/resend-verification", json=payload)
        assert response.status_code == 200
    with app.app_context():
        challenge = RegistrationChallenge.query.filter_by(email="resend@example.com").one()
        challenge.last_sent_at = datetime.now(timezone.utc) - timedelta(minutes=2)
        db.session.commit()
    assert client.post("/api/auth/resend-verification", json=payload).status_code == 429
