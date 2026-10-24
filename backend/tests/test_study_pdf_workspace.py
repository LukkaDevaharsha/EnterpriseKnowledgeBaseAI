from io import BytesIO

import pymupdf
import pytest
from flask_jwt_extended import create_access_token

from app import db
from app.models import Document, User


@pytest.fixture(autouse=True)
def deterministic_query_embedding(monkeypatch):
    from app.services import semantic_search

    monkeypatch.setattr(
        semantic_search, "generate_embeddings",
        lambda _texts, model_name=None, dimension=384: [
            [1.0] + [0.0] * (dimension - 1)
        ],
    )


def _user(app, email, employee_id, role="EMPLOYEE"):
    with app.app_context():
        user = User(
            name=email.split("@")[0], email=email, employee_id=employee_id,
            department="Research", role=role, is_active=True, is_verified=True,
            password_hash="test-hash",
        )
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))
        return {"Authorization": f"Bearer {token}"}, user.id


def _pdf_bytes(text, outline=()):
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), text)
    if outline:
        pdf.set_toc([[1, title, page_number] for title, page_number in outline])
    return pdf.tobytes()


def test_study_pdf_returns_real_outline_and_scoped_grounded_answer(
    client, app, monkeypatch
):
    from app.services import rag_service

    admin, _ = _user(app, "study-admin@example.test", "STUDY-ADMIN", "ADMIN")
    employee, employee_id = _user(app, "study-reader@example.test", "STUDY-READER")
    policy = "Employees may take annual leave and sick leave under the company leave policy."
    upload = client.post(
        "/api/admin/documents", headers=admin,
        data={"file": (BytesIO(_pdf_bytes(policy, [("Leave policy", 1)])), "leave.pdf")},
        content_type="multipart/form-data",
    )
    assert upload.status_code == 201, upload.get_json()
    document = upload.get_json()["document"]
    other_upload = client.post(
        "/api/admin/documents", headers=admin,
        data={"file": (BytesIO(_pdf_bytes("Other handbook: expenses need approval.")), "expenses.pdf")},
        content_type="multipart/form-data",
    )
    assert other_upload.status_code == 201, other_upload.get_json()
    other_document_id = other_upload.get_json()["document"]["id"]

    page_response = client.get(
        f"/api/study/documents/{document['id']}/pages", headers=employee
    )
    assert page_response.status_code == 200
    assert page_response.get_json()["outline"] == [
        {"level": 1, "title": "Leave policy", "page_number": 1}
    ]

    with app.app_context():
        app.config["STUDY_PDF_MODEL"] = "study-pdf-test-model"
        retrieved = rag_service.search_chunks(
            "What leave types does this policy mention?", employee_id, 5,
            document_id=document["id"],
        )
    assert retrieved
    assert retrieved[0]["document_id"] == document["id"]
    assert retrieved[0]["content"] == policy
    assert retrieved[0]["similarity_score"] >= app.config["RAG_MIN_SIMILARITY"]

    captured = {}

    def answer_model(question, evidence_json, system_prompt, model=None):
        import json

        captured["evidence"] = json.loads(evidence_json)
        captured["question"] = question
        captured["model"] = model
        return "The policy mentions annual leave and sick leave."

    monkeypatch.setattr(rag_service, "generate_chat_answer", answer_model)
    response = client.post(
        f"/api/study/documents/{document['id']}/ask", headers=employee,
        json={"question": "What leave types does this policy mention?"},
    )
    body = response.get_json()
    assert response.status_code == 200
    assert body["answer_type"] == "document_grounded"
    assert f'“{policy}” [S1]' in body["answer"]
    assert body["citations"][0]["document_id"] == document["id"]
    assert captured["evidence"][0]["document_id"] == document["id"]
    assert all(item["document_id"] != other_document_id for item in captured["evidence"])
    assert captured["evidence"][0]["excerpt"] == policy
    assert captured["model"] == "study-pdf-test-model"


def test_study_pdf_unrelated_question_returns_insufficient_evidence(
    client, app, monkeypatch
):
    from app.services import rag_service, semantic_search

    admin, _ = _user(app, "study-unrelated-admin@example.test", "STUDY-UNRELATED-ADMIN", "ADMIN")
    employee, _ = _user(app, "study-unrelated-reader@example.test", "STUDY-UNRELATED-READER")
    upload = client.post(
        "/api/admin/documents", headers=admin,
        data={"file": (BytesIO(_pdf_bytes("The paper studies blockchain healthcare records.")), "paper.pdf")},
        content_type="multipart/form-data",
    )
    document_id = upload.get_json()["document"]["id"]
    monkeypatch.setattr(
        semantic_search, "generate_embeddings",
        lambda texts, model_name=None, dimension=384: [
            [0.0, 1.0] + [0.0] * (dimension - 2) for _ in texts
        ],
    )
    model_calls = []
    monkeypatch.setattr(
        rag_service, "generate_chat_answer",
        lambda *args: model_calls.append(args) or "Unexpected answer. [S1]",
    )

    response = client.post(
        f"/api/study/documents/{document_id}/ask", headers=employee,
        json={"question": "What is the company's annual leave entitlement?"},
    )

    assert response.status_code == 200
    assert response.get_json()["insufficient_evidence"] is True
    assert response.get_json()["citations"] == []
    assert model_calls == []


def test_study_pdf_without_extracted_text_returns_actionable_error(client, app):
    admin, _ = _user(app, "study-empty-admin@example.test", "STUDY-EMPTY-ADMIN", "ADMIN")
    employee, _ = _user(app, "study-empty-reader@example.test", "STUDY-EMPTY-READER")
    upload = client.post(
        "/api/admin/documents", headers=admin,
        data={"file": (BytesIO(_pdf_bytes("Previously extracted text.")), "paper.pdf")},
        content_type="multipart/form-data",
    )
    document_id = upload.get_json()["document"]["id"]
    with app.app_context():
        document = db.session.get(Document, document_id)
        document.extracted_text = "  "
        db.session.commit()

    response = client.post(
        f"/api/study/documents/{document_id}/ask", headers=employee,
        json={"question": "What does this paper say?"},
    )

    assert response.status_code == 422
    assert "no extracted text" in response.get_json()["message"].lower()
    assert "ocr" in response.get_json()["message"].lower()


def test_study_pdf_page_render_highlights_text_and_preserves_authorization(client, app):
    admin, _ = _user(app, "render-admin@example.test", "RENDER-ADMIN", "ADMIN")
    owner, _ = _user(app, "render-owner@example.test", "RENDER-OWNER")
    reader, _ = _user(app, "render-reader@example.test", "RENDER-READER")
    shared_upload = client.post(
        "/api/admin/documents", headers=admin,
        data={"file": (BytesIO(_pdf_bytes("Annual leave is available to employees.")), "shared.pdf")},
        content_type="multipart/form-data",
    )
    private_upload = client.post(
        "/api/documents", headers=owner,
        data={"file": (BytesIO(_pdf_bytes("Private annual leave notes.")), "private.pdf")},
        content_type="multipart/form-data",
    )
    assert shared_upload.status_code == 201
    assert private_upload.status_code == 201
    shared_id = shared_upload.get_json()["document"]["id"]
    private_id = private_upload.get_json()["document"]["id"]

    endpoint = f"/api/study/documents/{shared_id}/pages/1/render"
    plain_page = client.get(endpoint, headers=reader)
    highlighted_page = client.get(
        endpoint, headers=reader, query_string={"query": "annual leave", "scale": "1.5"}
    )

    assert plain_page.status_code == 200
    assert plain_page.mimetype == "image/png"
    assert highlighted_page.status_code == 200
    assert highlighted_page.mimetype == "image/png"
    assert plain_page.data != highlighted_page.data

    unauthorized = client.get(endpoint)
    private_document = client.get(
        f"/api/study/documents/{private_id}/pages/1/render?query=annual",
        headers=reader,
    )
    assert unauthorized.status_code == 401
    assert private_document.status_code == 404


def test_study_pdf_scope_hides_other_users_private_documents(client, app):
    owner, _ = _user(app, "study-owner@example.test", "STUDY-OWNER")
    reader, _ = _user(app, "study-other@example.test", "STUDY-OTHER")
    uploaded = client.post(
        "/api/documents", headers=owner,
        data={"file": (BytesIO(_pdf_bytes("Private research notes.")), "private.pdf")},
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 201
    document_id = uploaded.get_json()["document"]["id"]

    response = client.post(
        f"/api/study/documents/{document_id}/ask", headers=reader,
        json={"question": "What do the notes say?"},
    )

    assert response.status_code == 404
    with app.app_context():
        assert db.session.get(Document, document_id).is_shared is False


def test_study_pdf_scope_abstains_when_model_cannot_cite_evidence(
    client, app, monkeypatch
):
    from app.services import rag_service

    admin, _ = _user(app, "study-abstain-admin@example.test", "STUDY-ABSTAIN-ADMIN", "ADMIN")
    employee, _ = _user(app, "study-abstain-reader@example.test", "STUDY-ABSTAIN-READER")
    uploaded = client.post(
        "/api/admin/documents", headers=admin,
        data={"file": (BytesIO(_pdf_bytes("The handbook describes leave categories.")), "handbook.pdf")},
        content_type="multipart/form-data",
    )
    document_id = uploaded.get_json()["document"]["id"]
    monkeypatch.setattr(
        rag_service, "generate_chat_answer",
        lambda *_args, **_kwargs: "The available documents do not contain enough relevant information to answer this question.",
    )

    response = client.post(
        f"/api/study/documents/{document_id}/ask", headers=employee,
        json={"question": "What is the precise annual leave entitlement?"},
    )

    assert response.status_code == 200
    assert response.get_json()["insufficient_evidence"] is True
    assert response.get_json()["citations"] == []
