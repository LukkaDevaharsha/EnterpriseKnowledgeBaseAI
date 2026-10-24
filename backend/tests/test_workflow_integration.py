"""End-to-end API coverage for the authenticated document-to-RAG workflow."""

from io import BytesIO

from app import db
from app.models import Document, DocumentChunk, User
from app.services import rag_service, semantic_search


LEAVE_POLICY = (
    "Employees may take annual leave and sick leave under the company leave policy."
)


def _register_and_login(client, app, *, suffix):
    payload = {
        "name": f"Workflow {suffix}",
        "email": f"workflow.{suffix}@example.com",
        "department": "Engineering",
        "password": "StrongPassword123",
    }
    registered = client.post("/api/auth/register", json=payload)
    assert registered.status_code == 202
    code = app.extensions["test_verification_outbox"][payload["email"]]
    registered = client.post("/api/auth/verify", json={"email": payload["email"], "code": code})
    assert registered.status_code == 201
    login = client.post(
        "/api/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login.status_code == 200
    return {
        "id": registered.get_json()["user"]["id"],
        "headers": {
            "Authorization": f"Bearer {login.get_json()['access_token']}"
        },
    }


def test_upload_search_and_rag_workflow_preserves_auth_and_grounding(
    client, app, monkeypatch
):
    owner = _register_and_login(client, app, suffix="owner")
    other = _register_and_login(client, app, suffix="other")

    # Keep both embedding stages deterministic and offline.
    vector = [1.0] + [0.0] * 383
    monkeypatch.setattr(
        semantic_search,
        "generate_embeddings",
        lambda texts, model_name=None, dimension=384: [vector for _ in texts],
    )

    chat_calls = []

    def fake_chat(question, evidence_json, system_prompt, model=None):
        chat_calls.append((question, evidence_json, system_prompt, model))
        if "how many days" in question.lower():
            return "The policy does not specify the number of days."
        return "Employees may take annual leave and sick leave. [S1]"

    monkeypatch.setattr(rag_service, "generate_chat_answer", fake_chat)

    # Authentication gates the API before document processing begins.
    assert client.post(
        "/api/documents",
        data={"file": (BytesIO(LEAVE_POLICY.encode()), "leave.txt")},
        content_type="multipart/form-data",
    ).status_code == 401

    upload = client.post(
        "/api/documents",
        headers=owner["headers"],
        data={
            "file": (BytesIO(LEAVE_POLICY.encode("utf-8")), "leave.txt"),
            "title": "Leave policy",
        },
        content_type="multipart/form-data",
    )
    assert upload.status_code == 201
    document_id = upload.get_json()["document"]["id"]
    assert upload.get_json()["document"]["status"] == "PROCESSED"

    with app.app_context():
        document = db.session.get(Document, document_id)
        chunks = DocumentChunk.query.filter_by(document_id=document_id).all()
        assert document.uploaded_by == owner["id"]
        assert document.extracted_text == LEAVE_POLICY
        assert len(chunks) == 1
        chunk = chunks[0]
        assert chunk.content == LEAVE_POLICY
        assert chunk.embedding_status == "PROCESSED"
        assert len(chunk.embedding) == app.config["EMBEDDING_DIMENSION"]
        chunk_id = chunk.id

    search = client.post(
        "/api/search",
        headers=owner["headers"],
        json={"query": "What types of leave may employees take?", "limit": 5},
    )
    assert search.status_code == 200
    search_body = search.get_json()
    assert search_body["count"] == 1
    assert search_body["results"][0]["document_id"] == document_id
    assert search_body["results"][0]["chunk_id"] == chunk_id
    assert search_body["results"][0]["content"] == LEAVE_POLICY

    answer = client.post(
        "/api/ask",
        headers=owner["headers"],
        json={"question": "What types of leave may employees take?", "top_k": 5},
    )
    answer_body = answer.get_json()
    assert answer.status_code == 200
    assert "annual leave" in answer_body["answer"].lower()
    assert "sick leave" in answer_body["answer"].lower()
    assert answer_body["insufficient_evidence"] is False
    assert answer_body["citations"] == [{
        "source_id": "S1",
        "document_id": document_id,
        "document_title": "Leave policy",
        "chunk_id": chunk_id,
        "chunk_index": 0,
        "excerpt": LEAVE_POLICY,
    }]

    abstention = client.post(
        "/api/ask",
        headers=owner["headers"],
        json={"question": "How many days of annual leave?"},
    )
    abstention_body = abstention.get_json()
    assert abstention.status_code == 200
    assert abstention_body["insufficient_evidence"] is True
    assert abstention_body["answer"] == rag_service.INSUFFICIENT_ANSWER
    assert abstention_body["citations"] == []
    assert len(chat_calls) == 2
    assert all(call[3] == app.config["COMPANY_KNOWLEDGE_MODEL"] for call in chat_calls)

    # Retrieval and document detail remain scoped to the authenticated owner.
    other_search = client.post(
        "/api/search",
        headers=other["headers"],
        json={"query": "leave policy"},
    )
    assert other_search.status_code == 200
    assert other_search.get_json()["results"] == []
    assert client.get(
        f"/api/documents/{document_id}", headers=other["headers"]
    ).status_code == 404

    with app.app_context():
        inactive = db.session.get(User, owner["id"])
        inactive.is_active = False
        db.session.commit()

    assert client.post(
        "/api/ask",
        headers=owner["headers"],
        json={"question": "What types of leave?"},
    ).status_code == 403
