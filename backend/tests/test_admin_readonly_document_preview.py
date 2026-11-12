"""Admin document preview is audited and cannot grant document capabilities."""
from flask_jwt_extended import create_access_token

from app import db
from app.models import AuditEvent, Conversation, Document, User


def make_user(app, email, employee_id, role="EMPLOYEE"):
    with app.app_context():
        user = User(name=email.split("@")[0], email=email, employee_id=employee_id,
                    department="Engineering", role=role, is_active=True,
                    is_verified=True, password_hash="test-hash")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))
        return {"Authorization": f"Bearer {token}"}, user.id


def test_admin_can_preview_user_document_and_preview_is_audited(client, app, monkeypatch):
    from app.routes import admin as admin_routes

    admin_headers, admin_id = make_user(app, "preview-admin@example.test", "PREV-ADMIN", role="ADMIN")
    _, owner_id = make_user(app, "preview-owner@example.test", "PREV-OWNER")
    with app.app_context():
        document = Document(title="Owner handbook", original_filename="handbook.pdf",
                            stored_filename="preview-doc-key", file_type="PDF", file_size=42,
                            status="PROCESSED", extracted_text="private extracted text",
                            uploaded_by=owner_id)
        db.session.add(document)
        db.session.commit()
        document_id = document.id

    class Storage:
        def read(self, key):
            assert key == "preview-doc-key"
            return b"opaque file bytes"

    monkeypatch.setattr(admin_routes, "get_storage", lambda: Storage())
    monkeypatch.setattr(admin_routes, "extract_document_pages", lambda content, kind: [(1, "Preview page text")])
    listing = client.get("/api/admin/user-documents", headers=admin_headers)
    assert listing.status_code == 200
    listed = next(row for row in listing.get_json()["documents"] if row["id"] == document_id)
    assert listed["owner"] == {"id": owner_id, "name": "preview-owner"}
    assert listed["created_at"]

    response = client.get(f"/api/admin/documents/{document_id}/preview", headers=admin_headers)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.get_json()["pages"] == [{"page_number": 1, "text": "Preview page text"}]
    assert "stored_filename" not in response.get_json()["document"]
    with app.app_context():
        event = AuditEvent.query.filter_by(action="document.preview", subject_id=str(document_id)).one()
        assert event.actor_user_id == admin_id
        assert event.details == {"document_owner_id": owner_id}


def test_admin_cannot_download_query_or_read_another_users_history(client, app):
    admin_headers, _ = make_user(app, "readonly-admin@example.test", "READ-ADMIN", role="ADMIN")
    owner_headers, owner_id = make_user(app, "readonly-owner@example.test", "READ-OWNER")
    with app.app_context():
        document = Document(title="Private handbook", original_filename="private.pdf",
                            stored_filename="private-doc-key", file_type="PDF", file_size=42,
                            status="PROCESSED", extracted_text="private text",
                            uploaded_by=owner_id)
        db.session.add(document)
        db.session.flush()
        conversation = Conversation(user_id=owner_id, document_id=document.id)
        db.session.add(conversation)
        db.session.commit()
        document_id, conversation_id = document.id, conversation.id

    assert client.get(f"/api/documents/{document_id}/download", headers=admin_headers).status_code == 403
    assert client.get(f"/api/study/documents/{document_id}/download", headers=admin_headers).status_code == 404
    assert client.get(f"/api/study/documents/{document_id}/pages", headers=admin_headers).status_code == 404
    assert client.post(f"/api/study/documents/{document_id}/ask", headers=admin_headers,
                       json={"question": "What is in the file?"}).status_code == 404
    assert client.get(f"/api/study/documents/{document_id}/conversations", headers=admin_headers).status_code == 404
    assert client.post("/api/ask", headers=admin_headers, json={"question": "Search documents"}).status_code == 403
    assert client.post("/api/search", headers=admin_headers, json={"query": "private text"}).status_code == 403
    assert client.get(f"/api/conversations/{conversation_id}", headers=admin_headers).status_code == 404

    metadata = client.get(f"/api/admin/documents/{document_id}", headers=admin_headers)
    assert metadata.status_code == 200
    assert "chunks" not in metadata.get_json()["document"]


def test_admin_baseai_answers_general_questions_without_rag(client, app, monkeypatch):
    from app.services import rag_extensions, rag_service

    admin_headers, _ = make_user(app, "general-admin@example.test", "GENERAL-ADMIN", role="ADMIN")
    monkeypatch.setattr(rag_extensions, "_general_answer", lambda question: {
        "answer": "General response", "citations": [],
        "insufficient_evidence": False, "answer_type": "general",
    })
    monkeypatch.setattr(rag_service, "search_chunks", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("RAG must not run for admins")))
    general = client.post("/api/ask", headers=admin_headers, json={"question": "What is photosynthesis?"})
    assert general.status_code == 200
    assert general.get_json()["answer_type"] == "general"
    assert client.post("/api/ask", headers=admin_headers,
                       json={"question": "What does the private handbook say?"}).status_code == 403
