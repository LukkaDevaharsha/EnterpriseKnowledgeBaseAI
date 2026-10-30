import logging

import pytest
from flask_jwt_extended import create_access_token

from app import create_app, db
from app.models import User
from app.services import gemini_client, ollama_client
from app.services.ollama_client import OllamaModelError, OllamaUnavailableError


def _set_gemini_config(app, monkeypatch, api_key="private-gemini-key-for-test"):
    for key, value in {
        "LLM_PROVIDER": "gemini",
        "GEMINI_API_KEY": api_key,
        "GEMINI_MODEL": "gemini-3.8-flash",
        "GENERAL_AI_MODEL": "gemini-3.8-flash",
        "GEMINI_TIMEOUT_SECONDS": 7,
    }.items():
        monkeypatch.setitem(app.config, key, value)


def _fake_gemini_client(monkeypatch, models):
    monkeypatch.setattr(
        "app.services.gemini_client.get_gemini_client",
        lambda: type("Client", (), {"models": models})(),
    )


@pytest.mark.parametrize(
    "status,provider_code,expected_error",
    [
        (401, "UNAUTHENTICATED", OllamaUnavailableError),
        (403, "PERMISSION_DENIED", OllamaUnavailableError),
        (429, "RESOURCE_EXHAUSTED", OllamaUnavailableError),
        (404, "NOT_FOUND", OllamaModelError),
    ],
)
def test_gemini_status_failures_log_only_sanitized_metadata(
    app, monkeypatch, caplog, status, provider_code, expected_error
):
    api_key = "private-gemini-key-for-test"
    question = "private user prompt marker 7d45"
    evidence = '[{"excerpt":"private document marker 9c21"}]'
    provider_message = (
        f"provider failure {provider_code}: key={api_key}; "
        f"question={question}; evidence={evidence}"
    )
    ApiFailure = type("GeminiApiFailure", (Exception,), {
        "code": status,
        "status": provider_code,
        "message": provider_message,
    })

    class Models:
        def generate_content(self, **_kwargs):
            raise ApiFailure()

    _set_gemini_config(app, monkeypatch, api_key)
    _fake_gemini_client(monkeypatch, Models())
    caplog.set_level(logging.WARNING, logger="app")

    with app.app_context(), pytest.raises(expected_error):
        ollama_client.generate_chat_answer(
            question, evidence, "private system prompt marker", model="gemini-3.8-flash"
        )

    log = caplog.text
    assert "provider=gemini" in log
    assert "model=gemini-3.8-flash" in log
    assert "exception_class=GeminiApiFailure" in log
    assert f"http_status={status}" in log
    assert f"provider_error_code={provider_code}" in log
    assert "api_key_configured=True" in log
    assert api_key not in log
    assert question not in log
    assert "private document marker 9c21" not in log
    assert "private system prompt marker" not in log


def test_missing_gemini_key_is_logged_as_boolean_and_stays_private(app, monkeypatch, caplog):
    _set_gemini_config(app, monkeypatch, api_key="")
    caplog.set_level(logging.WARNING, logger="app")

    with app.app_context(), pytest.raises(OllamaUnavailableError):
        ollama_client.generate_chat_answer(
            "private missing-key prompt", "[]", "system", model="gemini-3.8-flash"
        )

    assert "exception_class=RuntimeError" in caplog.text
    assert "api_key_configured=False" in caplog.text
    assert "private missing-key prompt" not in caplog.text
    assert "private-gemini-key" not in caplog.text


def test_gemini_timeout_is_sanitized_and_classified(app, monkeypatch, caplog):
    class Models:
        def generate_content(self, **_kwargs):
            raise TimeoutError("timeout included private prompt")

    _set_gemini_config(app, monkeypatch)
    _fake_gemini_client(monkeypatch, Models())
    caplog.set_level(logging.WARNING, logger="app")
    with app.app_context(), pytest.raises(OllamaUnavailableError):
        ollama_client.generate_chat_answer(
            "private timeout prompt", "[]", "system", model="gemini-3.8-flash"
        )

    assert "http_status=None" in caplog.text
    assert "provider_message=Gemini request timed out." in caplog.text
    assert "private timeout prompt" not in caplog.text


def test_gemini_success_returns_text_without_failure_log(app, monkeypatch, caplog):
    class Models:
        def generate_content(self, **kwargs):
            assert kwargs["model"] == "gemini-3.8-flash"
            return type("Response", (), {"text": "A safe answer."})()

    _set_gemini_config(app, monkeypatch)
    _fake_gemini_client(monkeypatch, Models())
    caplog.set_level(logging.WARNING, logger="app")
    with app.app_context():
        result = ollama_client.generate_chat_answer(
            "question", "[]", "system", model=app.config["GENERAL_AI_MODEL"]
        )
    assert result == "A safe answer."
    assert "Gemini generation failed" not in caplog.text


def test_gemini_sdk_initializes_with_backend_key_and_configured_timeout(app, monkeypatch):
    seen = {}
    _set_gemini_config(app, monkeypatch, "private-sdk-key")
    monkeypatch.setitem(app.extensions, "gemini_client", None)
    monkeypatch.setattr(
        gemini_client, "_create_client",
        lambda api_key, timeout_ms: seen.update(
            api_key=api_key, timeout_ms=timeout_ms
        ) or object(),
    )

    with app.app_context():
        client = gemini_client.get_gemini_client()

    assert seen == {"api_key": "private-sdk-key", "timeout_ms": 7000}
    assert app.extensions["gemini_client"] is client


def test_gemini_model_and_general_mode_resolve_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("JWT_SECRET_KEY", "config-test-key")
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", str(tmp_path / "files"))
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "private-config-test-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    monkeypatch.delenv("GENERAL_AI_MODEL", raising=False)

    configured = create_app({"TESTING": True})

    assert configured.config["LLM_PROVIDER"] == "gemini"
    assert configured.config["GEMINI_API_KEY"] == "private-config-test-key"
    assert configured.config["GEMINI_MODEL"] == "gemini-3.8-flash"
    assert configured.config["GENERAL_AI_MODEL"] == "gemini-3.8-flash"


def test_ask_keeps_generic_503_for_gemini_failure(client, app, monkeypatch, caplog):
    with app.app_context():
        user = User(
            name="Gemini Diagnostics", email="gemini-diagnostics@example.test",
            employee_id="GEM-DIAG", department="Support", role="EMPLOYEE",
            is_active=True, is_verified=True, password_hash="test-hash",
        )
        db.session.add(user)
        db.session.commit()
        headers = {"Authorization": f"Bearer {create_access_token(identity=str(user.id))}"}

    _set_gemini_config(app, monkeypatch)
    _fake_gemini_client(monkeypatch, type(
        "Models", (), {"generate_content": lambda *_a, **_k: (_ for _ in ()).throw(
            type("Error", (Exception,), {"code": 403, "message": "permission denied"})()
        )}
    )())
    caplog.set_level(logging.WARNING, logger="app")
    prompt = "Explain why the service exists marker p-481"
    response = client.post(
        "/api/ask", headers=headers,
        json={"question": prompt},
    )

    assert response.status_code == 503
    assert response.get_json()["message"] == "Question answering is temporarily unavailable."
    assert "private-gemini-key-for-test" not in response.get_data(as_text=True)
    assert "private-gemini-key-for-test" not in caplog.text
    assert prompt not in caplog.text
    assert "http_status=403" in caplog.text
