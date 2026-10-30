"""Provider dispatch tests with no network calls or API credentials."""

import json
import math
from urllib.error import HTTPError, URLError

import pytest

from app.services import embedding_service, email_sender, ollama_client
from app.services.email_sender import EmailDeliveryError
from app.services.email_sender import send_verification_code as deliver_verification_code
from app.services.embedding_service import EmbeddingError, embedding_model_identity
from app.services.ollama_client import OllamaModelError, OllamaUnavailableError


class FakeGeminiModels:
    def __init__(self, generation=None, embedding_factory=None, failure=None):
        self.generation = generation
        self.embedding_factory = embedding_factory
        self.failure = failure
        self.generation_calls = []
        self.embedding_calls = []

    def generate_content(self, **kwargs):
        self.generation_calls.append(kwargs)
        if self.failure:
            raise self.failure
        return type("Response", (), {"text": self.generation})()

    def embed_content(self, **kwargs):
        self.embedding_calls.append(kwargs)
        if self.failure:
            raise self.failure
        return self.embedding_factory(kwargs["contents"])


def test_provider_defaults_remain_local(monkeypatch, tmp_path):
    from app import create_app

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("JWT_SECRET_KEY", "provider-default-test-key")
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", str(tmp_path / "files"))
    for name in (
        "LLM_PROVIDER", "EMBEDDING_PROVIDER", "EMAIL_PROVIDER",
        "GENERAL_AI_MODEL", "COMPANY_KNOWLEDGE_MODEL", "STUDY_PDF_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    app = create_app({"TESTING": True})

    assert app.config["LLM_PROVIDER"] == "ollama"
    assert app.config["EMBEDDING_PROVIDER"] == "sentence_transformers"
    assert app.config["EMAIL_PROVIDER"] == "smtp"
    assert app.config["GENERAL_AI_MODEL"] == app.config["OLLAMA_MODEL"]
    assert app.config["COMPANY_KNOWLEDGE_MODEL"] == app.config["OLLAMA_MODEL"]
    assert app.config["STUDY_PDF_MODEL"] == app.config["OLLAMA_MODEL"]


def test_embedding_identity_separates_local_and_gemini_spaces(app, monkeypatch):
    with app.app_context():
        monkeypatch.setitem(app.config, "EMBEDDING_PROVIDER", "sentence_transformers")
        local_identity = embedding_model_identity("same-label", 384)
        monkeypatch.setitem(app.config, "EMBEDDING_PROVIDER", "gemini")
        gemini_identity = embedding_model_identity("same-label", 384)

    assert local_identity == "same-label"
    assert gemini_identity == "gemini:same-label:384"
    assert gemini_identity != local_identity


def test_gemini_generation_uses_mode_model_and_existing_prompt_fields(app, monkeypatch):
    models = FakeGeminiModels(generation="Grounded answer [S1]")
    monkeypatch.setattr(
        "app.services.gemini_client.get_gemini_client",
        lambda: type("Client", (), {"models": models})(),
    )
    with app.app_context():
        for key, value in {
            "LLM_PROVIDER": "gemini", "GEMINI_MODEL": "gemini-fallback",
            "GENERAL_AI_MODEL": "gemini-general",
            "COMPANY_KNOWLEDGE_MODEL": "gemini-company",
            "STUDY_PDF_MODEL": "gemini-study",
        }.items():
            monkeypatch.setitem(app.config, key, value)
        answers = [
            ollama_client.generate_chat_answer("q", "[]", "system", model=app.config[key])
            for key in ("GENERAL_AI_MODEL", "COMPANY_KNOWLEDGE_MODEL", "STUDY_PDF_MODEL")
        ]

    assert answers == ["Grounded answer [S1]"] * 3
    assert [call["model"] for call in models.generation_calls] == [
        "gemini-general", "gemini-company", "gemini-study"
    ]
    assert models.generation_calls[0]["contents"].startswith("Question:\nq")
    assert models.generation_calls[0]["config"]["system_instruction"] == "system"
    assert models.generation_calls[0]["config"]["max_output_tokens"] == 1024


@pytest.mark.parametrize(
    "failure, expected",
    [
        (type("Api404", (Exception,), {"code": 404})(), OllamaModelError),
        (type("Api429", (Exception,), {"code": 429})(), OllamaUnavailableError),
        (TimeoutError("secret-free timeout"), OllamaUnavailableError),
    ],
)
def test_gemini_generation_failures_are_sanitized(app, monkeypatch, failure, expected):
    models = FakeGeminiModels(failure=failure)
    monkeypatch.setattr(
        "app.services.gemini_client.get_gemini_client",
        lambda: type("Client", (), {"models": models})(),
    )
    with app.app_context():
        app.config.update({"LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "private"})
        with pytest.raises(expected) as raised:
            ollama_client.generate_chat_answer("q", "[]", "system", model="gemini-test")
    assert "private" not in str(raised.value)
    assert "secret-free timeout" not in str(raised.value)


def _gemini_embedding_app(app, monkeypatch, models):
    monkeypatch.setattr(
        "app.services.gemini_client.get_gemini_client",
        lambda: type("Client", (), {"models": models})(),
    )
    for key, value in {
        "EMBEDDING_PROVIDER": "gemini",
        "EMBEDDING_MODEL_NAME": "gemini-embedding-2",
        "EMBEDDING_DIMENSION": 384,
        "GEMINI_API_KEY": "private-test-key",
    }.items():
        monkeypatch.setitem(app.config, key, value)


def test_gemini_embeddings_request_384_batch_and_normalize(app, monkeypatch):
    models = FakeGeminiModels(embedding_factory=lambda texts: type(
        "Response", (), {"embeddings": [type("Embedding", (), {"values": [2.0] + [0.0] * 383})() for _ in texts]}
    )())
    with app.app_context():
        _gemini_embedding_app(app, monkeypatch, models)
        vectors = embedding_service.generate_embeddings(
            [f"text {index}" for index in range(35)]
        )

    assert len(vectors) == 35
    assert all(len(vector) == 384 for vector in vectors)
    assert all(math.isclose(math.sqrt(sum(x * x for x in v)), 1.0) for v in vectors)
    assert [len(call["contents"]) for call in models.embedding_calls] == [32, 3]
    assert all(call["config"]["output_dimensionality"] == 384 for call in models.embedding_calls)
    assert all(call["model"] == "gemini-embedding-2" for call in models.embedding_calls)


@pytest.mark.parametrize(
    "values, message",
    [([1.0] * 383, "dimension mismatch"), ([float("nan")] + [0.0] * 383, "non-finite")],
)
def test_gemini_embeddings_reject_invalid_vectors(app, monkeypatch, values, message):
    models = FakeGeminiModels(embedding_factory=lambda _texts: type(
        "Response", (), {"embeddings": [type("Embedding", (), {"values": values})()]}
    )())
    with app.app_context():
        _gemini_embedding_app(app, monkeypatch, models)
        with pytest.raises(EmbeddingError, match=message):
            embedding_service.generate_embeddings("sample")


def test_gemini_embedding_api_failure_is_safe(app, monkeypatch):
    models = FakeGeminiModels(failure=RuntimeError("api key private-test-key"))
    with app.app_context():
        _gemini_embedding_app(app, monkeypatch, models)
        with pytest.raises(EmbeddingError) as raised:
            embedding_service.generate_embeddings("sample")
    assert "private-test-key" not in str(raised.value)
    assert "api key" not in str(raised.value)


class FakeHttpResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size=-1):
        return b'{"id":"email-id"}'


def test_resend_uses_mocked_https_api_and_keeps_otp_body_private(app, monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["headers"] = request.headers
        seen["payload"] = json.loads(request.data)
        seen["timeout"] = timeout
        return FakeHttpResponse()

    monkeypatch.setattr(email_sender, "urlopen", fake_urlopen)
    with app.app_context():
        for key, value in {
            "EMAIL_PROVIDER": "resend", "RESEND_API_KEY": "private-resend-key",
            "RESEND_FROM_EMAIL": "accounts@example.test", "RESEND_TIMEOUT_SECONDS": 4,
        }.items():
            monkeypatch.setitem(app.config, key, value)
        deliver_verification_code("employee@example.test", "123456")

    assert seen["url"] == "https://api.resend.com/emails"
    assert seen["headers"]["Authorization"] == "Bearer private-resend-key"
    assert seen["payload"]["from"] == "accounts@example.test"
    assert seen["payload"]["to"] == ["employee@example.test"]
    assert "123456" in seen["payload"]["text"]
    assert seen["timeout"] == 4


@pytest.mark.parametrize(
    "failure, category",
    [
        (HTTPError("https://api.resend.com/emails", 403, "private body", {}, None), "resend_rejection"),
        (TimeoutError("private timeout"), "resend_timeout"),
        (URLError("network private detail"), "resend_connection"),
    ],
)
def test_resend_errors_are_sanitized(app, monkeypatch, failure, category):
    monkeypatch.setattr(email_sender, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(failure))
    with app.app_context():
        for key, value in {
            "EMAIL_PROVIDER": "resend", "RESEND_API_KEY": "private-key",
            "RESEND_FROM_EMAIL": "accounts@example.test",
        }.items():
            monkeypatch.setitem(app.config, key, value)
        with pytest.raises(EmailDeliveryError) as raised:
            deliver_verification_code("employee@example.test", "123456")
    assert raised.value.category == category
    assert "private" not in str(raised.value)


def test_resend_missing_configuration_does_not_call_network(app, monkeypatch):
    monkeypatch.setattr(email_sender, "urlopen", lambda *_a, **_k: pytest.fail("network call"))
    with app.app_context():
        for key, value in {
            "EMAIL_PROVIDER": "resend", "RESEND_API_KEY": "", "RESEND_FROM_EMAIL": "",
        }.items():
            monkeypatch.setitem(app.config, key, value)
        with pytest.raises(EmailDeliveryError) as raised:
            deliver_verification_code("employee@example.test", "123456")
    assert raised.value.category == "missing_configuration"
    assert set(raised.value.missing_settings) == {"RESEND_API_KEY", "RESEND_FROM_EMAIL"}
