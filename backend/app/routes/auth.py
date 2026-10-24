"""Authentication routes for the Enterprise Knowledge Base AI Assistant."""

import logging
import re
from werkzeug.security import generate_password_hash
from sqlalchemy import func

from flask import Blueprint, jsonify, request
from flask_jwt_extended import (
    create_access_token,
    get_jwt_identity,
    jwt_required,
)
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import User
from app.models import RegistrationChallenge
from app.services import email_sender
from app.services.employee_ids import next_employee_id
from app.services.registration import (
    MAX_RESENDS, OTP_ATTEMPTS, OTP_TTL, RESEND_DELAY,
    code_matches, create_code, hash_code, now_utc,
)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")
logger = logging.getLogger(__name__)

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _error(message, status_code=400, errors=None):
    """Build a consistent JSON error response."""
    payload = {"status": "error", "message": message}
    if errors:
        payload["errors"] = errors
    return jsonify(payload), status_code


def _json_payload():
    """Return the request JSON object or an error response."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, _error(
            "Request body must be a valid JSON object.", 400
        )
    return data, None


def _clean_text(value, field_name, max_length=None, required=True):
    """Validate and normalize a text field."""
    if value is None:
        if required:
            return None, f"{field_name} is required."
        return None, None

    if not isinstance(value, str):
        return None, f"{field_name} must be a string."

    value = value.strip()
    if required and not value:
        return None, f"{field_name} is required."
    if max_length is not None and len(value) > max_length:
        return None, f"{field_name} must be at most {max_length} characters."
    return value, None


@auth_bp.post("/register")
def register():
    """Create a pending account and deliver an expiring email code."""
    data, error_response = _json_payload()
    if error_response is not None:
        return error_response

    errors = {}

    name, error = _clean_text(
        data.get("name"), "name", max_length=120
    )
    if error:
        errors["name"] = error

    email, error = _clean_text(
        data.get("email"), "email", max_length=255
    )
    if error:
        errors["email"] = error
    elif not EMAIL_PATTERN.fullmatch(email):
        errors["email"] = "email must be a valid email address."
    else:
        email = email.lower()

    department, error = _clean_text(
        data.get("department"), "department", max_length=100
    )
    if error:
        errors["department"] = error

    password = data.get("password")
    if not isinstance(password, str):
        errors["password"] = "password is required."
    elif len(password) < 8 or len(password) > 128:
        errors["password"] = (
            "password must be between 8 and 128 characters."
        )

    if errors:
        return _error("Validation failed.", 400, errors)

    # Reject duplicate accounts before attempting to insert.
    if User.query.filter_by(email=email).first() is not None:
        return _error(
            "An account with this email or employee ID already exists.",
            409,
        )
    if RegistrationChallenge.query.filter_by(email=email).first() is not None:
        return _error("Registration is already pending for this email.", 409)

    code = create_code()
    now = now_utc()
    challenge = RegistrationChallenge(
        email=email, name=name, department=department,
        password_hash=generate_password_hash(password),
        code_hash=hash_code(email, code), expires_at=now + OTP_TTL,
        attempts=0, resend_count=0, last_sent_at=now,
    )
    try:
        db.session.add(challenge)
        email_sender.send_verification_code(email, code)
        db.session.commit()
    except email_sender.EmailDeliveryError as exc:
        db.session.rollback()
        logger.warning(
            "Registration verification email failed: category=%s missing_settings=%s "
            "smtp_code=%s os_error=%s",
            exc.category, ",".join(exc.missing_settings) or "none",
            exc.smtp_code if exc.smtp_code is not None else "none",
            exc.os_error if exc.os_error is not None else "none",
        )
        return _error("Verification email is temporarily unavailable. Try again later.", 503)
    except IntegrityError:
        db.session.rollback()
        return _error("Registration is already pending for this email.", 409)

    return jsonify({
        "status": "success",
        "message": "A verification code has been sent to your email.",
    }), 202


@auth_bp.post("/verify")
def verify_registration():
    data, error_response = _json_payload()
    if error_response is not None:
        return error_response
    email = data.get("email")
    code = data.get("code")
    if not isinstance(email, str) or not EMAIL_PATTERN.fullmatch(email.strip()):
        return _error("A valid email address is required.", 400)
    email = email.strip().lower()
    if not isinstance(code, str) or not re.fullmatch(r"\d{6}", code):
        return _error("The verification code must be six digits.", 400)

    challenge = RegistrationChallenge.query.filter_by(email=email).with_for_update().first()
    if challenge is None:
        return _error("Registration code is invalid or expired.", 400)
    now = now_utc()
    if challenge.expires_at <= now:
        db.session.delete(challenge)
        db.session.commit()
        return _error("Registration code is invalid or expired.", 400)
    if challenge.attempts >= OTP_ATTEMPTS:
        db.session.delete(challenge)
        db.session.commit()
        return _error("Too many verification attempts. Register again.", 429)
    if not code_matches(email, code, challenge.code_hash):
        challenge.attempts += 1
        exhausted = challenge.attempts >= OTP_ATTEMPTS
        if exhausted:
            db.session.delete(challenge)
        db.session.commit()
        if exhausted:
            return _error("Too many verification attempts. Register again.", 429)
        return _error("The verification code is incorrect.", 400)

    user = User(
        name=challenge.name, email=challenge.email,
        employee_id=next_employee_id(), department=challenge.department,
        password_hash=challenge.password_hash, role="EMPLOYEE",
        is_active=True, is_verified=True,
    )
    try:
        db.session.add(user)
        db.session.delete(challenge)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _error("An account with this email already exists.", 409)
    return jsonify({
        "status": "success", "message": "Email verified. Your employee account is ready.",
        "user": user.to_dict(),
    }), 201


@auth_bp.post("/resend-verification")
def resend_verification():
    data, error_response = _json_payload()
    if error_response is not None:
        return error_response
    email = data.get("email")
    generic = {"status": "success", "message": "If registration is pending, a new code will be sent when allowed."}
    if not isinstance(email, str) or not EMAIL_PATTERN.fullmatch(email.strip()):
        return jsonify(generic), 200
    email = email.strip().lower()
    challenge = RegistrationChallenge.query.filter_by(email=email).with_for_update().first()
    if challenge is None:
        return jsonify(generic), 200
    now = now_utc()
    if challenge.expires_at <= now:
        db.session.delete(challenge)
        db.session.commit()
        return jsonify(generic), 200
    elapsed = now - challenge.last_sent_at
    if elapsed < RESEND_DELAY:
        return _error("Please wait before requesting another verification code.", 429)
    if challenge.resend_count >= MAX_RESENDS:
        return _error("The resend limit was reached. Register again.", 429)
    code = create_code()
    challenge.code_hash = hash_code(email, code)
    challenge.last_sent_at = now
    challenge.resend_count += 1
    challenge.attempts = 0
    challenge.expires_at = now + OTP_TTL
    try:
        email_sender.send_verification_code(email, code)
        db.session.commit()
    except email_sender.EmailDeliveryError as exc:
        db.session.rollback()
        logger.warning(
            "Verification email resend failed: category=%s missing_settings=%s "
            "smtp_code=%s os_error=%s",
            exc.category, ",".join(exc.missing_settings) or "none",
            exc.smtp_code if exc.smtp_code is not None else "none",
            exc.os_error if exc.os_error is not None else "none",
        )
        return _error("Verification email is temporarily unavailable. Try again later.", 503)
    return jsonify(generic), 200


@auth_bp.post("/login")
def login():
    """Authenticate a user and return an access token."""
    data, error_response = _json_payload()
    if error_response is not None:
        return error_response

    identifier, identifier_error = _clean_text(
        data.get("identifier", data.get("email")), "identifier", max_length=255, required=True
    )
    if identifier_error:
        return _error("Validation failed.", 400, {"identifier": identifier_error})

    password = data.get("password")
    if not isinstance(password, str) or not password:
        return _error(
            "Validation failed.",
            400,
            {"password": "password is required."},
        )

    is_email = "@" in identifier
    user = User.query.filter_by(
        email=identifier.lower() if is_email else "__no_email__"
    ).first()
    if user is None and not is_email:
        user = User.query.filter(func.upper(User.employee_id) == identifier.upper()).first()
    if user is None or not user.check_password(password):
        return _error("Invalid email or password.", 401)

    if not user.is_active:
        return _error("Account is deactivated.", 403)
    if not user.is_verified:
        return _error("Email address has not been verified.", 403)

    access_token = create_access_token(identity=str(user.id))

    return (
        jsonify(
            {
                "status": "success",
                "message": "Login successful.",
                "access_token": access_token,
                "user": user.to_dict(),
            }
        ),
        200,
    )


@auth_bp.get("/me")
@jwt_required()
def profile():
    """Return the profile of the authenticated user."""
    identity = get_jwt_identity()

    try:
        user_id = int(identity)
    except (TypeError, ValueError):
        return _error("Invalid authentication token.", 401)

    user = db.session.get(User, user_id)
    if user is None:
        return _error("User account not found.", 404)
    if not user.is_active:
        return _error("Account is deactivated.", 403)
    if not user.is_verified:
        return _error("Email address has not been verified.", 403)

    return (
        jsonify(
            {
                "status": "success",
                "user": user.to_dict(),
            }
        ),
        200,
    )
