"""Embedding generator and persistence integration tests."""

import math

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models import Document, DocumentChunk, User
from app.services import chunk_embedding_pipeline, embedding_service
from app.services.embedding_service import EmbeddingError


def test_reembed_cli_reports_empty_corpus(app):
    result = app.test_cli_runner().invoke(args=["reembed-chunks"])

    assert result.exit_code == 0
    assert "No document chunks found" in result.output
    assert "All document chunks have embeddings" not in result.output


class FakeModel:
    def __init__(self, output=None, failure=None):
        self.output = output
        self.failure = failure
        self.received = None

    def encode(self, texts, **kwargs):
        self.received = (texts, kwargs)
        if self.failure:
            raise self.failure
        return self.output


def test_embedding_service_generates_valid_normalized_batch(monkeypatch):
    fake = FakeModel([[3.0, 4.0], [0.0, 2.0]])
    monkeypatch.setattr(embedding_service, "_load_model", lambda name: fake)
    embedding_service._models.pop("fake-model", None)

    vectors = embedding_service.generate_embeddings(
        ["  first\ntext ", "second"], model_name="fake-model", dimension=2
    )

    assert fake.received[0] == ["first text", "second"]
    assert vectors == [[0.6, 0.8], [0.0, 1.0]]
    assert math.isclose(math.sqrt(sum(value * value for value in vectors[0])), 1.0)


@pytest.mark.parametrize("texts", ["  ", ["ok", " \n"]])
def test_embedding_service_rejects_empty_text(texts):
    with pytest.raises(EmbeddingError, match="Empty"):
        embedding_service.generate_embeddings(texts, model_name="empty-test")


def test_embedding_service_rejects_wrong_dimension(monkeypatch):
    monkeypatch.setattr(embedding_service, "_load_model", lambda name: FakeModel([[1, 2]]))
    embedding_service._models.pop("dimension-test", None)
    with pytest.raises(EmbeddingError, match="dimension mismatch"):
        embedding_service.generate_embeddings("text", "dimension-test", 3)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_embedding_service_rejects_non_finite_values(monkeypatch, value):
    model_name = f"nonfinite-{value}"
    monkeypatch.setattr(
        embedding_service, "_load_model", lambda name: FakeModel([[value, 1.0]])
    )
    embedding_service._models.pop(model_name, None)
    with pytest.raises(EmbeddingError, match="non-finite"):
        embedding_service.generate_embeddings("text", model_name, 2)


def test_model_loading_failure_is_actionable(monkeypatch):
    def fail(name):
        raise EmbeddingError("model unavailable; install model assets")

    monkeypatch.setattr(embedding_service, "_load_model", fail)
    embedding_service._models.pop("load-failure", None)
    with pytest.raises(EmbeddingError, match="model unavailable"):
        embedding_service.generate_embeddings("text", "load-failure", 2)


def test_inference_failure_is_reported(monkeypatch):
    monkeypatch.setattr(
        embedding_service,
        "_load_model",
        lambda name: FakeModel(failure=OSError("offline")),
    )
    embedding_service._models.pop("inference-failure", None)
    with pytest.raises(EmbeddingError, match="inference failed"):
        embedding_service.generate_embeddings("text", "inference-failure", 2)


@pytest.fixture
def embedding_document(app):
    with app.app_context():
        user = User(
            name="Embedding User",
            email="embedding@example.com",
            employee_id="EMB001",
            department="Engineering",
            role="EMPLOYEE",
            is_active=True,
        )
        user.set_password("StrongPassword123")
        db.session.add(user)
        db.session.flush()
        document = Document(
            title="Embedding source",
            original_filename="source.txt",
            stored_filename="embedding-test-file",
            file_type="TXT",
            file_size=13,
            status="PROCESSED",
            extracted_text="first chunk second chunk",
            uploaded_by=user.id,
        )
        db.session.add(document)
        db.session.flush()
        chunks = [
            DocumentChunk(
                document_id=document.id,
                chunk_index=index,
                content=content,
                start_char=index * 12,
                end_char=index * 12 + len(content),
            )
            for index, content in enumerate(("first chunk", "second chunk"))
        ]
        db.session.add_all(chunks)
        db.session.commit()
        yield document.id


def test_embeddings_persist_for_correct_chunks_and_are_not_duplicated(
    app, embedding_document, monkeypatch
):
    calls = []

    def generator(texts, model_name=None, dimension=None):
        calls.append((list(texts), model_name))
        return [[1.0] + [0.0] * (dimension - 1) for _ in texts]

    monkeypatch.setattr(chunk_embedding_pipeline, "generate_embeddings", generator)
    with app.app_context():
        app.config["EMBEDDING_MODEL_NAME"] = "fixture-model-v1"
        assert chunk_embedding_pipeline.process_document_embeddings(embedding_document)
        assert chunk_embedding_pipeline.process_document_embeddings(embedding_document)
        chunks = DocumentChunk.query.filter_by(
            document_id=embedding_document
        ).order_by(DocumentChunk.chunk_index).all()
        assert len(calls) == 1
        assert len(calls[0][0]) == 2
        assert [chunk.embedding_status for chunk in chunks] == ["PROCESSED"] * 2
        assert [chunk.embedding_model for chunk in chunks] == ["fixture-model-v1"] * 2
        assert all(len(chunk.embedding) == 384 for chunk in chunks)
        assert all(chunk.embedding[0] == 1.0 for chunk in chunks)
        assert all(chunk.embedding_content_hash for chunk in chunks)


def test_embedding_failure_keeps_chunks_and_marks_failed(
    app, embedding_document, monkeypatch
):
    def fail(*args, **kwargs):
        raise EmbeddingError("fixture inference error")

    monkeypatch.setattr(chunk_embedding_pipeline, "generate_embeddings", fail)
    with app.app_context():
        app.config["EMBEDDING_MODEL_NAME"] = "fixture-failed-model"
        assert not chunk_embedding_pipeline.process_document_embeddings(embedding_document)
        chunks = DocumentChunk.query.filter_by(
            document_id=embedding_document
        ).order_by(DocumentChunk.chunk_index).all()
        assert len(chunks) == 2
        assert all(chunk.embedding_status == "FAILED" for chunk in chunks)
        assert all(chunk.embedding is None for chunk in chunks)


def test_partial_embedding_commit_rolls_back_and_can_retry(
    app, embedding_document, monkeypatch
):
    original_commit = db.session.commit
    commit_count = 0

    def fail_once():
        nonlocal commit_count
        commit_count += 1
        if commit_count == 2:
            raise SQLAlchemyError("fixture database failure")
        return original_commit()

    monkeypatch.setattr(db.session, "commit", fail_once)
    with app.app_context():
        app.config["EMBEDDING_MODEL_NAME"] = "fixture-retry-model"
        assert not chunk_embedding_pipeline.process_document_embeddings(embedding_document)
        chunks = DocumentChunk.query.filter_by(
            document_id=embedding_document
        ).all()
        assert len(chunks) == 2
        assert all(chunk.embedding is None for chunk in chunks)
        assert all(chunk.embedding_status == "FAILED" for chunk in chunks)

        monkeypatch.setattr(db.session, "commit", original_commit)
        assert chunk_embedding_pipeline.process_document_embeddings(embedding_document)
        assert DocumentChunk.query.filter_by(
            document_id=embedding_document, embedding_status="PROCESSED"
        ).count() == 2


def test_model_change_is_blocked_without_explicit_reembedding(
    app, embedding_document, monkeypatch
):
    monkeypatch.setattr(
        chunk_embedding_pipeline,
        "generate_embeddings",
        lambda texts, model_name=None, dimension=384: [
            [1.0] + [0.0] * (dimension - 1) for _ in texts
        ],
    )
    with app.app_context():
        app.config["EMBEDDING_MODEL_NAME"] = "model-v1"
        assert chunk_embedding_pipeline.process_document_embeddings(embedding_document)
        app.config["EMBEDDING_MODEL_NAME"] = "model-v2"
        assert not chunk_embedding_pipeline.process_document_embeddings(embedding_document)
        assert chunk_embedding_pipeline.reembed_all_chunks()
        assert set(db.session.query(DocumentChunk.embedding_model).distinct().all()) == {
            ("model-v2",)
        }
