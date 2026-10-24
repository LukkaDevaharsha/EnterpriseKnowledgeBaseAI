"""Semantic search service, API, and document ownership tests."""

import hashlib
from datetime import timedelta

import pytest
from flask_jwt_extended import create_access_token
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models import Document, DocumentChunk, User
from app.services import semantic_search
from app.services.embedding_service import EmbeddingError
from app.services.semantic_search import SearchDatabaseError


MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DIMENSION = 384


def vector(first, second=0.0):
    return [first, second] + [0.0] * (DIMENSION - 2)


def add_chunk(document, index, content, embedding, model=MODEL, status="PROCESSED"):
    return DocumentChunk(
        document_id=document.id,
        chunk_index=index,
        content=content,
        start_char=index * 20,
        end_char=index * 20 + len(content),
        embedding=embedding,
        embedding_model=model,
        embedding_content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        embedding_status=status,
    )


@pytest.fixture
def search_data(app):
    with app.app_context():
        app.config["EMBEDDING_MODEL_NAME"] = MODEL
        owner = User(
            name="Search Owner", email="search.owner@example.com",
            employee_id="SRCH001", department="Engineering", role="EMPLOYEE",
            is_active=True,
        )
        other = User(
            name="Other Owner", email="search.other@example.com",
            employee_id="SRCH002", department="Finance", role="EMPLOYEE",
            is_active=True,
        )
        inactive = User(
            name="Inactive Owner", email="search.inactive@example.com",
            employee_id="SRCH003", department="Finance", role="EMPLOYEE",
            is_active=False,
        )
        for user in (owner, other, inactive):
            user.password_hash = "fixture-password-hash"
        db.session.add_all((owner, other, inactive))
        db.session.flush()

        owner_doc = Document(
            title="Leave policy", original_filename="leave.txt",
            stored_filename="search-leave-owner", file_type="TXT", file_size=30,
            status="PROCESSED", extracted_text="Annual leave allowance information.",
            uploaded_by=owner.id,
        )
        owner_doc2 = Document(
            title="Benefits handbook", original_filename="benefits.txt",
            stored_filename="search-benefits-owner", file_type="TXT", file_size=20,
            status="PROCESSED", extracted_text="Health coverage and benefits.",
            uploaded_by=owner.id,
        )
        private_doc = Document(
            title="Private salary document", original_filename="salary.txt",
            stored_filename="search-private-other", file_type="TXT", file_size=28,
            status="PROCESSED", extracted_text="Private salary confidential content.",
            uploaded_by=other.id,
        )
        db.session.add_all((owner_doc, owner_doc2, private_doc))
        db.session.flush()
        db.session.add_all((
            add_chunk(owner_doc, 0, "Annual leave allowance information.", vector(1.0)),
            add_chunk(owner_doc, 1, "Sick leave and medical absences.", vector(0.8, 0.6)),
            add_chunk(owner_doc2, 0, "Health coverage and benefits.", vector(-1.0)),
            add_chunk(private_doc, 0, "Private salary confidential content.", vector(1.0)),
            # These must be excluded regardless of their vector score.
            add_chunk(owner_doc2, 1, "Old model embedding.", vector(1.0), model="old-model"),
            add_chunk(owner_doc2, 2, "Pending embedding.", None, status="PENDING"),
        ))
        db.session.commit()

        return {
            "owner_id": owner.id,
            "other_id": other.id,
            "inactive_id": inactive.id,
            "owner_token": create_access_token(identity=str(owner.id)),
            "other_token": create_access_token(identity=str(other.id)),
            "inactive_token": create_access_token(identity=str(inactive.id)),
            "expired_token": create_access_token(
                identity=str(owner.id), expires_delta=timedelta(seconds=-1)
            ),
            "owner_doc_id": owner_doc.id,
            "private_doc_id": private_doc.id,
        }


def install_query_embedding(monkeypatch, result=None, error=None):
    calls = []

    def generate(texts, model_name=None, dimension=None):
        calls.append((texts, model_name, dimension))
        if error:
            raise error
        return [result if result is not None else vector(1.0)]

    monkeypatch.setattr(semantic_search, "generate_embeddings", generate)
    return calls


def test_service_ranks_cosine_similarity_and_applies_limit(
    app, search_data, monkeypatch
):
    calls = install_query_embedding(monkeypatch)
    with app.app_context():
        assert db.session.query(DocumentChunk).filter_by(
            document_id=search_data["owner_doc_id"], embedding_status="PROCESSED"
        ).count() >= 2
        results = semantic_search.search_chunks("  leave policy ", search_data["owner_id"], 2)

    assert calls == [(["leave policy"], MODEL, DIMENSION)]
    assert [item["chunk_index"] for item in results] == [0, 1]
    assert results[0]["similarity_score"] == pytest.approx(1.0)
    assert results[1]["similarity_score"] == pytest.approx(0.8)
    assert len(results) == 2
    assert results[0]["document_title"] == "Leave policy"


def test_service_returns_empty_for_no_eligible_chunks(app, search_data, monkeypatch):
    calls = install_query_embedding(monkeypatch)
    with app.app_context():
        results = semantic_search.search_chunks("anything", 987654)
    assert results == []
    assert calls == []


def test_service_stably_breaks_similarity_ties(app, search_data, monkeypatch):
    with app.app_context():
        doc = db.session.get(Document, search_data["owner_doc_id"])
        db.session.add(add_chunk(doc, 2, "Tie chunk.", vector(1.0)))
        db.session.commit()
        install_query_embedding(monkeypatch)
        results = semantic_search.search_chunks("query", search_data["owner_id"], 10)
    top = [item for item in results if item["similarity_score"] == pytest.approx(1.0)]
    assert [(item["document_id"], item["chunk_index"]) for item in top] == sorted(
        (item["document_id"], item["chunk_index"]) for item in top
    )


@pytest.mark.parametrize(
    "bad_vector, message",
    [
        ([1.0], "dimension mismatch"),
        ([float("nan")] + [0.0] * (DIMENSION - 1), "non-finite"),
        ([float("inf")] + [0.0] * (DIMENSION - 1), "non-finite"),
        ([0.0] * DIMENSION, "zero or invalid"),
    ],
)
def test_service_rejects_invalid_query_embedding(
    app, search_data, monkeypatch, bad_vector, message
):
    install_query_embedding(monkeypatch, result=bad_vector)
    with app.app_context(), pytest.raises(EmbeddingError, match=message):
        semantic_search.search_chunks("query", search_data["owner_id"])


def test_service_excludes_malformed_stored_embeddings(app, search_data, monkeypatch):
    install_query_embedding(monkeypatch)
    with app.app_context():
        doc = db.session.get(Document, search_data["owner_doc_id"])
        malformed = add_chunk(doc, 3, "Malformed legacy vector.", vector(1.0))
        malformed.embedding = [float("nan")] + [0.0] * (DIMENSION - 1)
        db.session.add(malformed)
        db.session.commit()
        results = semantic_search.search_chunks("query", search_data["owner_id"], 20)
    assert all(item["content"] != "Malformed legacy vector." for item in results)


def test_search_api_returns_only_owner_authorized_results(
    client, search_data, monkeypatch
):
    install_query_embedding(monkeypatch)
    response = client.post(
        "/api/search",
        headers={"Authorization": f"Bearer {search_data['owner_token']}"},
        json={"query": "What leave time can employees take?", "limit": 5},
    )
    body = response.get_json()
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["query"] == "What leave time can employees take?"
    assert body["count"] == len(body["results"]) == 3
    assert all(result["document_id"] != search_data["private_doc_id"] for result in body["results"])
    serialized = str(body)
    assert "Private salary document" not in serialized
    assert "Private salary confidential content" not in serialized
    assert "stored_filename" not in serialized
    assert "similarity_score" in body["results"][0]


@pytest.mark.parametrize(
    "payload",
    [None, {}, {"query": ""}, {"query": "  "}, {"query": 12},
     {"query": "x" * 2001}, {"query": "x", "limit": "2"},
     {"query": "x", "limit": True}, {"query": "x", "limit": 0},
     {"query": "x", "limit": 21}, {"query": "x", "limit": 1.5}],
)
def test_search_api_rejects_invalid_requests(client, search_data, payload):
    response = client.post(
        "/api/search",
        headers={"Authorization": f"Bearer {search_data['owner_token']}"},
        json=payload,
    )
    assert response.status_code == 400
    assert response.get_json()["status"] == "error"


def test_search_api_rejects_invalid_json(client, search_data):
    response = client.post(
        "/api/search",
        headers={"Authorization": f"Bearer {search_data['owner_token']}"},
        data="{invalid",
        content_type="application/json",
    )
    assert response.status_code == 400


@pytest.mark.parametrize("token_key", [None, "expired_token", "invalid_token"])
def test_search_api_requires_valid_authentication(client, search_data, token_key):
    headers = {}
    if token_key == "invalid_token":
        headers["Authorization"] = "Bearer not-a-valid-token"
    elif token_key:
        headers["Authorization"] = f"Bearer {search_data[token_key]}"
    response = client.post("/api/search", headers=headers, json={"query": "leave"})
    assert response.status_code == 401


def test_search_api_rejects_inactive_user(client, search_data):
    response = client.post(
        "/api/search",
        headers={"Authorization": f"Bearer {search_data['inactive_token']}"},
        json={"query": "leave"},
    )
    assert response.status_code == 403


def test_search_api_handles_no_results(client, search_data, monkeypatch):
    install_query_embedding(monkeypatch)
    from flask_jwt_extended import create_access_token
    with client.application.app_context():
        empty_user = User(
            name="Empty Search User", email="empty.search@example.com",
            employee_id="SRCH004", department="Engineering", role="EMPLOYEE",
            is_active=True,
        )
        empty_user.password_hash = "fixture-password-hash"
        db.session.add(empty_user)
        db.session.commit()
        token = create_access_token(identity=str(empty_user.id))
    response = client.post(
        "/api/search",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "some query"},
    )
    assert response.status_code == 200
    assert response.get_json()["results"] == []
    assert response.get_json()["count"] == 0


def test_search_api_handles_embedding_failure(client, search_data, monkeypatch):
    install_query_embedding(monkeypatch, error=EmbeddingError("private internal detail"))
    response = client.post(
        "/api/search",
        headers={"Authorization": f"Bearer {search_data['owner_token']}"},
        json={"query": "leave"},
    )
    assert response.status_code == 503
    assert "private internal detail" not in response.get_data(as_text=True)


@pytest.mark.parametrize("failure_type", [SearchDatabaseError, SQLAlchemyError])
def test_search_api_handles_database_failure(
    client, search_data, monkeypatch, failure_type
):
    from app.routes import search as search_routes

    def fail(*args, **kwargs):
        raise failure_type("secret")

    monkeypatch.setattr(search_routes, "search_chunks", fail)
    response = client.post(
        "/api/search",
        headers={"Authorization": f"Bearer {search_data['owner_token']}"},
        json={"query": "leave"},
    )
    assert response.status_code == 503
    assert "secret" not in response.get_data(as_text=True)


def test_search_api_rejects_unknown_user_identity(client):
    with client.application.app_context():
        token = create_access_token(identity="987654")
    response = client.post(
        "/api/search",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "leave"},
    )
    assert response.status_code == 403
