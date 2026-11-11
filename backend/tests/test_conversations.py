"""Conversation history persistence and ownership tests."""

from flask_jwt_extended import create_access_token

from app import db
from app.models import User


def test_conversation_messages_persist_and_remain_user_scoped(client, app):
    with app.app_context():
        owner = User(
            name="Conversation Owner", email="conversation-owner@example.test",
            employee_id="CONV001", department="Engineering",
            password_hash="fixture-password-hash",
        )
        other = User(
            name="Other User", email="conversation-other@example.test",
            employee_id="CONV002", department="Finance",
            password_hash="fixture-password-hash",
        )
        db.session.add_all((owner, other))
        db.session.flush()
        owner_token = create_access_token(identity=str(owner.id))
        other_token = create_access_token(identity=str(other.id))
        db.session.commit()

    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    other_headers = {"Authorization": f"Bearer {other_token}"}

    created = client.post("/api/conversations", headers=owner_headers, json={})
    assert created.status_code == 201
    conversation_id = created.get_json()["id"]

    saved_message = client.post(
        f"/api/conversations/{conversation_id}/messages",
        headers=owner_headers,
        json={
            "role": "user",
            "content": "Where is the leave policy?",
            "citations": [{"document_id": 7}],
            "metadata": {"source": "test"},
        },
    )
    assert saved_message.status_code == 201
    assert saved_message.get_json()["content"] == "Where is the leave policy?"

    history = client.get(
        f"/api/conversations/{conversation_id}", headers=owner_headers
    )
    assert history.status_code == 200
    body = history.get_json()
    assert body["title"] == "Where is the leave policy?"
    assert len(body["messages"]) == 1
    assert body["messages"][0]["citations"] == [{"document_id": 7}]
    assert body["messages"][0]["metadata"] == {"source": "test"}

    assert client.get(
        f"/api/conversations/{conversation_id}", headers=other_headers
    ).status_code == 404

    with app.app_context():
        from app.models import ConversationMessage

        persisted = ConversationMessage.query.filter_by(
            conversation_id=conversation_id
        ).one()
        assert persisted.content == "Where is the leave policy?"
