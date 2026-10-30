from sqlalchemy.engine import make_url
import pytest

from app import create_app
from app.utils.database_url import render_database_url


def _database_config(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("JWT_SECRET_KEY", "database-config-test-key")
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", str(tmp_path / "database-files"))
    monkeypatch.setenv("DB_USER", "pooler_user")
    monkeypatch.setenv("DB_PASSWORD", "private-test-password")
    monkeypatch.setenv("DB_HOST", "db.example")
    monkeypatch.setenv("DB_PORT", "6543")
    monkeypatch.setenv("DB_NAME", "knowledge")
    return make_url(create_app({"TESTING": True}).config["SQLALCHEMY_DATABASE_URI"])


def test_database_url_supports_required_sslmode(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_SSLMODE", "require")

    url = _database_config(monkeypatch, tmp_path)

    assert url.drivername == "postgresql+psycopg"
    assert url.username == "pooler_user"
    assert url.password == "private-test-password"
    assert url.host == "db.example"
    assert url.port == 6543
    assert url.database == "knowledge"
    assert url.query == {"sslmode": "require"}
    assert "private-test-password" not in render_database_url(url)


def test_database_url_without_sslmode_preserves_local_defaults(monkeypatch, tmp_path):
    monkeypatch.delenv("DB_SSLMODE", raising=False)

    url = _database_config(monkeypatch, tmp_path)

    assert url.query == {}
    assert url.host == "db.example"
    assert url.port == 6543
    assert url.database == "knowledge"


def test_database_url_rendering_masks_password_and_preserves_other_parts():
    url = make_url(
        "postgresql+psycopg://audit_user:never-print-this@db.example:5432/knowledge"
    )

    rendered = render_database_url(url)

    assert "never-print-this" not in rendered
    assert "audit_user" in rendered
    assert "db.example:5432/knowledge" in rendered
    assert "***" in rendered


def test_production_disables_debug_even_when_flask_debug_is_enabled(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FLASK_DEBUG", "true")
    monkeypatch.setenv("JWT_SECRET_KEY", "production-test-key-" + "x" * 40)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://client.example")
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", str(tmp_path / "production-files"))

    app = create_app({"TESTING": True, "DEBUG": True})

    assert app.config["APP_ENV"] == "production"
    assert app.config["DEBUG"] is False


def test_production_rejects_short_jwt_secret_without_echoing_it(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "short-secret-test-value")

    try:
        create_app({"TESTING": True})
    except RuntimeError as exc:
        assert str(exc) == (
            "JWT_SECRET_KEY must contain at least 32 bytes in production."
        )
        assert "short-secret-test-value" not in str(exc)
    else:
        raise AssertionError("Production accepted a short JWT secret.")


def test_development_debug_defaults_on_and_can_be_disabled(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    development_app = create_app({"TESTING": True})
    assert development_app.config["DEBUG"] is True

    monkeypatch.setenv("FLASK_DEBUG", "false")
    non_debug_app = create_app({"TESTING": True})
    assert non_debug_app.config["DEBUG"] is False


def test_document_storage_path_can_be_configured_without_changing_default(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", str(tmp_path / "persistent"))

    app = create_app({"TESTING": True})

    assert app.config["DOCUMENT_STORAGE_PATH"] == str(tmp_path / "persistent")


def test_ai_modes_use_independent_models_when_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("JWT_SECRET_KEY", "mode-model-test-key")
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", str(tmp_path / "models"))
    monkeypatch.setenv("OLLAMA_MODEL", "shared-model")
    monkeypatch.setenv("GENERAL_AI_MODEL", "general-model")
    monkeypatch.setenv("COMPANY_KNOWLEDGE_MODEL", "company-model")
    monkeypatch.setenv("STUDY_PDF_MODEL", "study-model")

    app = create_app({"TESTING": True})

    assert app.config["GENERAL_AI_MODEL"] == "general-model"
    assert app.config["COMPANY_KNOWLEDGE_MODEL"] == "company-model"
    assert app.config["STUDY_PDF_MODEL"] == "study-model"


@pytest.mark.parametrize("blank_value", [None, "", "   "])
def test_ai_mode_models_fall_back_to_ollama_model(
    monkeypatch, tmp_path, blank_value
):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("JWT_SECRET_KEY", "mode-model-test-key")
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", str(tmp_path / "models"))
    monkeypatch.setenv("OLLAMA_MODEL", "shared-model")
    for key in ("GENERAL_AI_MODEL", "COMPANY_KNOWLEDGE_MODEL", "STUDY_PDF_MODEL"):
        if blank_value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, blank_value)

    app = create_app({"TESTING": True, "OLLAMA_MODEL": "override-shared-model"})

    assert app.config["OLLAMA_MODEL"] == "override-shared-model"
    assert app.config["GENERAL_AI_MODEL"] == "override-shared-model"
    assert app.config["COMPANY_KNOWLEDGE_MODEL"] == "override-shared-model"
    assert app.config["STUDY_PDF_MODEL"] == "override-shared-model"


def _create_cors_test_app(monkeypatch, tmp_path, environment, origins=None):
    monkeypatch.setenv("APP_ENV", environment)
    monkeypatch.setenv("JWT_SECRET_KEY", "test-key-not-for-production-" + "x" * 20)
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", str(tmp_path / "documents"))
    if origins is None:
        monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", origins)
    return create_app({"TESTING": True})


def test_cors_allows_only_configured_origins_and_does_not_bypass_jwt(
    monkeypatch, tmp_path
):
    app = _create_cors_test_app(
        monkeypatch,
        tmp_path,
        "development",
        " http://localhost:5173,https://portal.example, http://localhost:5173 ",
    )
    client = app.test_client()

    assert app.config["CORS_ALLOWED_ORIGINS"] == [
        "http://localhost:5173",
        "https://portal.example",
    ]
    allowed = client.get(
        "/api/health", headers={"Origin": "http://localhost:5173"}
    )
    assert allowed.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"

    disallowed = client.get(
        "/api/health", headers={"Origin": "https://unknown.example"}
    )
    assert "Access-Control-Allow-Origin" not in disallowed.headers

    unauthenticated = client.post(
        "/api/ask",
        headers={"Origin": "http://localhost:5173"},
        json={"question": "What is the policy?"},
    )
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["Access-Control-Allow-Origin"] == (
        "http://localhost:5173"
    )


def test_development_without_cors_configuration_does_not_allow_all_origins(
    monkeypatch, tmp_path
):
    app = _create_cors_test_app(monkeypatch, tmp_path, "development")

    response = app.test_client().get(
        "/api/health", headers={"Origin": "https://arbitrary.example"}
    )

    assert app.config["CORS_ALLOWED_ORIGINS"] == []
    assert "Access-Control-Allow-Origin" not in response.headers


@pytest.mark.parametrize(
    "origins",
    [
        None,
        "",
        "https://client.example/path",
        "http://client.example",
        "https://*.example.com",
        "https://client.example:0",
    ],
)
def test_production_requires_valid_https_cors_origin_configuration(
    monkeypatch, tmp_path, origins
):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "production-test-key-" + "x" * 40)
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", str(tmp_path / "production-files"))
    if origins is None:
        monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", origins)

    with pytest.raises(RuntimeError, match="CORS_ALLOWED_ORIGINS"):
        create_app({"TESTING": True})


def test_production_requires_explicit_document_storage_path(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "production-test-key-" + "x" * 40)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://client.example")
    monkeypatch.delenv("DOCUMENT_STORAGE_PATH", raising=False)

    with pytest.raises(RuntimeError, match="DOCUMENT_STORAGE_PATH"):
        create_app({"TESTING": True})


def test_storage_path_creation_or_write_failure_is_safe(monkeypatch, tmp_path):
    blocked_path = tmp_path / "not-a-directory"
    blocked_path.write_text("occupied", encoding="utf-8")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", str(blocked_path))

    with pytest.raises(RuntimeError) as exc_info:
        create_app({"TESTING": True})

    assert str(exc_info.value) == (
        "DOCUMENT_STORAGE_PATH must be a writable directory."
    )
    assert str(blocked_path) not in str(exc_info.value)


def test_development_runner_refuses_production(monkeypatch):
    import run

    monkeypatch.setitem(run.app.config, "APP_ENV", "production")
    with pytest.raises(RuntimeError, match="limited to development"):
        run.run_development_server()


def test_development_runner_uses_frontend_proxy_port(monkeypatch):
    import run

    monkeypatch.setitem(run.app.config, "APP_ENV", "development")
    monkeypatch.setitem(run.app.config, "DEBUG", False)
    calls = []
    monkeypatch.setattr(run.app, "run", lambda **kwargs: calls.append(kwargs))

    run.run_development_server()

    assert calls == [{"debug": False, "port": 8000}]
