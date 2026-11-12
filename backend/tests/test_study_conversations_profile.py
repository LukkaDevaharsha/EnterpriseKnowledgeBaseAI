"""Tests for document-scoped Study chats and self-service profile editing."""
from flask_jwt_extended import create_access_token

from app import db
from app.models import Conversation, Document, User


def _user(name, email, employee_id):
    user = User(name=name, email=email, employee_id=employee_id,
                department="Engineering", password_hash="fixture-password-hash")
    db.session.add(user)
    db.session.flush()
    return user


def _document(user):
    document = Document(title="Guide", original_filename="guide.pdf",
                        stored_filename="study-guide-key", file_type="PDF",
                        file_size=10, status="PROCESSED", extracted_text="Guide text",
                        uploaded_by=user.id)
    db.session.add(document)
    db.session.flush()
    return document


def test_document_conversations_are_scoped_and_hidden_from_baseai(client, app):
    with app.app_context():
        owner = _user("Study Owner", "study-owner@example.test", "STUDY001")
        other = _user("Other", "study-other@example.test", "STUDY002")
        document = _document(owner)
        general_chat = Conversation(user_id=owner.id)
        db.session.add(general_chat)
        db.session.flush()
        document_id = document.id
        general_chat_id = general_chat.id
        owner_token = create_access_token(identity=str(owner.id))
        other_token = create_access_token(identity=str(other.id))
        db.session.commit()
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    other_headers = {"Authorization": f"Bearer {other_token}"}

    created = client.post(f"/api/study/documents/{document_id}/conversations", headers=owner_headers, json={})
    assert created.status_code == 201
    chat_id = created.get_json()["id"]
    assert created.get_json()["document_id"] == document_id
    assert client.get(f"/api/study/documents/{document_id}/conversations/{chat_id}", headers=owner_headers).status_code == 200
    assert client.get(f"/api/study/documents/{document_id}/conversations", headers=other_headers).status_code == 404
    assert client.get(f"/api/study/documents/{document_id}/conversations/{chat_id}", headers=other_headers).status_code == 404
    baseai_chats = client.get("/api/conversations", headers=owner_headers).get_json()["conversations"]
    assert [chat["id"] for chat in baseai_chats] == [general_chat_id]
    assert all(chat["id"] != chat_id for chat in baseai_chats)
    assert client.delete(f"/api/study/documents/{document_id}/conversations/{chat_id}", headers=owner_headers).status_code == 200


def test_document_chat_persists_messages_and_uses_document_only_rag(client, app, monkeypatch):
    from app.routes import study_conversations
    calls = []
    def answer(question, user_id, top_k, document_id=None):
        calls.append((question, user_id, document_id))
        return {"answer": "Grounded answer [S1]", "citations": [{"source_id": "S1", "document_id": document_id}], "insufficient_evidence": False}
    monkeypatch.setattr(study_conversations.rag_service, "answer_question", answer)
    with app.app_context():
        owner = _user("Chat Owner", "chat-owner@example.test", "CHAT001")
        document = _document(owner)
        token = create_access_token(identity=str(owner.id))
        owner_id, document_id = owner.id, document.id
        db.session.commit()
    headers = {"Authorization": f"Bearer {token}"}
    first = client.post(f"/api/study/documents/{document_id}/chat", headers=headers, json={"question": "Explain this guide"})
    assert first.status_code == 200
    body = first.get_json()
    conversation_id = body["conversation"]["id"]
    assert body["conversation"]["title"] == "Explain this guide"
    assert len(body["messages"]) == 2
    followup = client.post(f"/api/study/documents/{document_id}/chat", headers=headers, json={"question": "Tell me more", "conversation_id": conversation_id})
    assert followup.status_code == 200
    assert "Explain this guide" in calls[-1][0]
    assert calls[-1][2] == document_id
    history = client.get(f"/api/study/documents/{document_id}/conversations/{conversation_id}", headers=headers).get_json()
    assert len(history["messages"]) == 4
    assert history["messages"][1]["citations"][0]["document_id"] == document_id


def test_profile_update_changes_only_supported_fields(client, app):
    with app.app_context():
        user = _user("Profile Owner", "profile-owner@example.test", "PROF001")
        token = create_access_token(identity=str(user.id))
        user_id = user.id
        db.session.commit()
    headers = {"Authorization": f"Bearer {token}"}
    updated = client.patch("/api/auth/me", headers=headers, json={"name": "Updated Name", "department": "Research"})
    assert updated.status_code == 200
    assert updated.get_json()["user"]["name"] == "Updated Name"
    assert updated.get_json()["user"]["department"] == "Research"
    assert client.patch("/api/auth/me", headers=headers, json={"role": "ADMIN"}).status_code == 400
    with app.app_context():
        user = db.session.get(User, user_id)
        assert user.role == "EMPLOYEE"
        assert user.email == "profile-owner@example.test"
