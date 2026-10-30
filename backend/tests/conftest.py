"""Pytest configuration for backend tests."""

import os
import sys
import tempfile
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv(
    os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        ".env",
    )
)

import pytest

from app import create_app, db


def _test_database_uri():
    user = quote(os.getenv("DB_USER", "postgres"), safe="")
    password = quote(os.getenv("DB_PASSWORD", ""), safe="")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")

    test_db_name = (
        os.getenv("DB_NAME", "enterprise_knowledge_base")
        + "_test"
    )

    return (
        f"postgresql+psycopg://{user}:{password}"
        f"@{host}:{port}/{test_db_name}"
    )


@pytest.fixture(scope="session")
def app():
    with tempfile.TemporaryDirectory(
        prefix="knowledge-base-test-"
    ) as storage_dir:

        application = create_app(
            {
                "SQLALCHEMY_DATABASE_URI": _test_database_uri(),
                "TESTING": True,
                # Keep regression fixtures deterministic even when developer
                # or deployment provider variables are present in the shell.
                "LLM_PROVIDER": "ollama",
                "EMBEDDING_PROVIDER": "sentence_transformers",
                "EMAIL_PROVIDER": "smtp",
                "DOCUMENT_STORAGE_PATH": storage_dir,
                # Allow multipart overhead while testing the 10 MB
                # individual-file limit.
                "MAX_CONTENT_LENGTH": 11 * 1024 * 1024,
            }
        )

        with application.app_context():
            db.create_all()

        yield application

        with application.app_context():
            db.session.remove()
            db.drop_all()


@pytest.fixture(autouse=True)
def clean_storage(app):
    storage_path = app.config["DOCUMENT_STORAGE_PATH"]
    os.makedirs(storage_path, exist_ok=True)

    for filename in os.listdir(storage_path):
        file_path = os.path.join(storage_path, filename)

        if os.path.isfile(file_path):
            os.remove(file_path)

    yield

    for filename in os.listdir(storage_path):
        file_path = os.path.join(storage_path, filename)

        if os.path.isfile(file_path):
            os.remove(file_path)


@pytest.fixture(autouse=True)
def mock_embedding_generation(monkeypatch):
    """Keep the suite offline and exercise persistence with deterministic vectors."""
    from app.services import chunk_embedding_pipeline

    monkeypatch.setattr(
        chunk_embedding_pipeline,
        "generate_embeddings",
        lambda texts, model_name=None, dimension=384: [
            [1.0] + [0.0] * (dimension - 1) for _ in texts
        ],
    )


@pytest.fixture(autouse=True)
def capture_test_verification_codes(app, monkeypatch):
    """Keep OTP tests deterministic without SMTP or logging plaintext codes."""
    from app.services import email_sender

    outbox = {}
    app.extensions["test_verification_outbox"] = outbox
    monkeypatch.setattr(
        email_sender,
        "send_verification_code",
        lambda recipient, code: outbox.__setitem__(recipient.lower(), code),
    )

@pytest.fixture(autouse=True)
def clean_database(app, clean_storage):
    yield

    with app.app_context():
        db.session.remove()

        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())

        db.session.commit()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def reset_cloud_provider_selection(app):
    """Prevent deployment shell settings from changing legacy regression tests."""
    defaults = {
        "LLM_PROVIDER": "ollama",
        "EMBEDDING_PROVIDER": "sentence_transformers",
        "EMAIL_PROVIDER": "smtp",
    }
    app.config.update(defaults)
    yield
