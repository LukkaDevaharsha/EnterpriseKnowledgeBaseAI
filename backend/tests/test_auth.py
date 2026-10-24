"""Tests for authentication and health endpoints."""

import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask_jwt_extended import create_access_token

BASE_URL = "http://localhost"
VALID_USER = {
    "name": "Test User",
    "email": "test.user@example.com",
    "password": "StrongPassword123",
    "department": "Engineering",
}


def register_verified(client, app, payload):
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 202
    code = app.extensions["test_verification_outbox"][payload["email"].lower()]
    verified = client.post("/api/auth/verify", json={"email": payload["email"], "code": code})
    assert verified.status_code == 201
    return verified


def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "success"


def test_db_health_endpoint(client):
    response = client.get("/api/db-health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "success"


def test_register_success(client, app):
    response = client.post("/api/auth/register", json=VALID_USER)
    assert response.status_code == 202
    assert "user" not in response.get_json()
    response = client.post("/api/auth/verify", json={
        "email": VALID_USER["email"],
        "code": app.extensions["test_verification_outbox"][VALID_USER["email"]],
    })
    assert response.status_code == 201
    data = response.get_json()
    assert data["status"] == "success"
    assert "password_hash" not in data["user"]
    assert data["user"]["role"] == "EMPLOYEE"
    assert data["user"]["is_active"] is True
    assert data["user"]["is_verified"] is True
    assert data["user"]["employee_id"].startswith("EMP")

    from app.models import User

    with app.app_context():
        user = User.query.filter_by(email=VALID_USER["email"]).first()
        assert user is not None
        assert user.password_hash != VALID_USER["password"]
        assert user.check_password(VALID_USER["password"])


def test_registration_response_does_not_contain_password_hash(client):
    payload = dict(VALID_USER, email="nohash@example.com")
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 202
    raw = response.get_data(as_text=True)
    assert "password_hash" not in raw
    assert "StrongPassword123" not in raw


def test_duplicate_email(client):
    client.post("/api/auth/register", json=VALID_USER)
    duplicate = dict(VALID_USER)
    response = client.post("/api/auth/register", json=duplicate)
    assert response.status_code == 409


def test_employee_id_is_generated_not_taken_from_public_input(client, app):
    first = register_verified(client, app, dict(VALID_USER, employee_id="EMP000001"))
    second_payload = dict(VALID_USER, email="other@example.com", employee_id="EMP000001")
    second = register_verified(client, app, second_payload)
    assert first.get_json()["user"]["employee_id"] != second.get_json()["user"]["employee_id"]


def test_missing_fields_rejected(client):
    response = client.post("/api/auth/register", json={"name": "Only Name"})
    assert response.status_code == 400


def test_invalid_email_rejected(client):
    payload = dict(VALID_USER, email="not-an-email")
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 400


def test_short_and_long_passwords_rejected(client):
    short_payload = dict(VALID_USER, password="short", email="short@example.com")
    assert client.post("/api/auth/register", json=short_payload).status_code == 400

    long_password = "a" * 129
    long_payload = dict(VALID_USER, password=long_password, email="long@example.com")
    assert client.post("/api/auth/register", json=long_payload).status_code == 400


def test_role_admin_cannot_be_self_assigned(client, app):
    payload = dict(VALID_USER, email="admin-attempt@example.com", role="ADMIN")
    response = client.post("/api/auth/register", json=payload)
    code = app.extensions["test_verification_outbox"][payload["email"]]
    verified = client.post("/api/auth/verify", json={"email": payload["email"], "code": code})
    assert verified.status_code == 201
    assert verified.get_json()["user"]["role"] == "EMPLOYEE"


def test_role_manager_cannot_be_self_assigned(client, app):
    payload = dict(VALID_USER, email="manager-attempt@example.com", role="MANAGER")
    response = client.post("/api/auth/register", json=payload)
    code = app.extensions["test_verification_outbox"][payload["email"]]
    verified = client.post("/api/auth/verify", json={"email": payload["email"], "code": code})
    assert response.status_code == 202
    assert verified.status_code == 201
    assert verified.get_json()["user"]["role"] == "EMPLOYEE"


def test_is_active_false_cannot_be_self_assigned(client, app):
    payload = dict(VALID_USER, email="inactive-attempt@example.com", is_active=False)
    response = client.post("/api/auth/register", json=payload)
    code = app.extensions["test_verification_outbox"][payload["email"]]
    verified = client.post("/api/auth/verify", json={"email": payload["email"], "code": code})
    assert response.status_code == 202
    assert verified.get_json()["user"]["is_active"] is True


def test_malformed_json_rejected(client):
    response = client.post(
        "/api/auth/register",
        data="not-json",
        content_type="text/plain",
    )
    assert response.status_code == 400


def test_login_success(client, app):
    register_verified(client, app, VALID_USER)
    response = client.post(
        "/api/auth/login",
        json={"email": VALID_USER["email"], "password": VALID_USER["password"]},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"
    assert "access_token" in data
    assert "password_hash" not in str(data)


def test_login_wrong_password(client, app):
    register_verified(client, app, VALID_USER)
    response = client.post(
        "/api/auth/login",
        json={"email": VALID_USER["email"], "password": "WrongPassword999"},
    )
    assert response.status_code == 401


def test_login_unknown_email_generic_message(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "unknown@example.com", "password": "AnyPassword123"},
    )
    assert response.status_code == 401
    assert (
        response.get_json()["message"]
        == "Invalid email or password."
    )


def test_login_email_normalized(client, app):
    register_verified(client, app, VALID_USER)
    response = client.post(
        "/api/auth/login",
        json={"email": VALID_USER["email"].upper(), "password": VALID_USER["password"]},
    )
    assert response.status_code == 200


def test_login_by_generated_employee_id(client, app):
    registered = register_verified(client, app, VALID_USER)
    employee_id = registered.get_json()["user"]["employee_id"]
    response = client.post("/api/auth/login", json={
        "identifier": employee_id.lower(), "password": VALID_USER["password"],
    })
    assert response.status_code == 200
    assert "access_token" in response.get_json()


def test_pending_challenge_is_not_an_authenticated_account(client, app):
    response = client.post("/api/auth/register", json=VALID_USER)
    assert response.status_code == 202
    login = client.post("/api/auth/login", json={
        "identifier": VALID_USER["email"], "password": VALID_USER["password"],
    })
    assert login.status_code == 401
    assert "user" not in response.get_json()


def test_inactive_user_cannot_login(client, app):
    register_verified(client, app, VALID_USER)
    from app.models import User

    with app.app_context():
        user = User.query.filter_by(email=VALID_USER["email"]).first()
        user.is_active = False
        from app import db

        db.session.commit()

    response = client.post(
        "/api/auth/login",
        json={"email": VALID_USER["email"], "password": VALID_USER["password"]},
    )
    assert response.status_code == 403


def test_profile_requires_token(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_profile_rejects_invalid_token(client):
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer definitely-not-a-token"},
    )
    assert response.status_code == 401


def test_profile_rejects_expired_token(client, app):
    expired_token = None
    with app.app_context():
        expired_token = create_access_token(
            identity="1", expires_delta=timedelta(seconds=-1)
        )
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == 401


def test_profile_success(client, app):
    register_verified(client, app, VALID_USER)
    login_response = client.post(
        "/api/auth/login",
        json={"email": VALID_USER["email"], "password": VALID_USER["password"]},
    )
    token = login_response.get_json()["access_token"]
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["user"]["email"] == VALID_USER["email"].lower()
    assert "password_hash" not in data["user"]


def test_profile_rejects_inactive_user(client, app):
    register_verified(client, app, VALID_USER)
    login_response = client.post(
        "/api/auth/login",
        json={"email": VALID_USER["email"], "password": VALID_USER["password"]},
    )
    token = login_response.get_json()["access_token"]

    from app import db
    from app.models import User

    with app.app_context():
        user = User.query.filter_by(email=VALID_USER["email"]).first()
        user.is_active = False
        db.session.commit()

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_responses_never_expose_password_hashes(client, app):
    register_verified(client, app, VALID_USER)
    login_response = client.post(
        "/api/auth/login",
        json={"email": VALID_USER["email"], "password": VALID_USER["password"]},
    )
    token = login_response.get_json()["access_token"]

    for response in [
        login_response,
        client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}),
    ]:
        text = response.get_data(as_text=True)
        assert "password_hash" not in text
        assert VALID_USER["password"] not in text
