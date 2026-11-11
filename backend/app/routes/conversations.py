"""User-owned conversation history and public read-only shares."""
import secrets

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app import db
from app.models import Conversation, ConversationMessage, User

conversations_bp = Blueprint("conversations", __name__, url_prefix="/api/conversations")


def _owned(conversation_id):
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return None
    return Conversation.query.filter_by(id=conversation_id, user_id=user_id).first()


@conversations_bp.get("")
@jwt_required()
def list_conversations():
    rows = Conversation.query.filter_by(user_id=int(get_jwt_identity())).order_by(
        Conversation.is_pinned.desc(), Conversation.updated_at.desc()).all()
    return jsonify({"conversations": [row.to_dict() for row in rows]})


@conversations_bp.post("")
@jwt_required()
def create_conversation():
    conversation = Conversation(user_id=int(get_jwt_identity()))
    db.session.add(conversation)
    db.session.commit()
    return jsonify(conversation.to_dict(include_messages=True)), 201


@conversations_bp.get("/<int:conversation_id>")
@jwt_required()
def get_conversation(conversation_id):
    conversation = _owned(conversation_id)
    if conversation is None:
        return jsonify({"message": "Conversation not found."}), 404
    if conversation.is_locked:
        return jsonify({"message": "Unlock this conversation from the sidebar before opening it."}), 423
    return jsonify(conversation.to_dict(include_messages=True))


@conversations_bp.post("/<int:conversation_id>/messages")
@jwt_required()
def add_message(conversation_id):
    conversation = _owned(conversation_id)
    if conversation is None:
        return jsonify({"message": "Conversation not found."}), 404
    if conversation.is_locked or conversation.is_archived:
        return jsonify({"message": "This conversation cannot be updated while locked or archived."}), 423
    payload = request.get_json(silent=True) or {}
    role, content = payload.get("role"), payload.get("content")
    if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip() or len(content) > 50000:
        return jsonify({"message": "A valid message role and content are required."}), 400
    citations = payload.get("citations", [])
    metadata = payload.get("metadata", {})
    if not isinstance(citations, list) or not isinstance(metadata, dict):
        return jsonify({"message": "Message citations and metadata have invalid formats."}), 400
    message = ConversationMessage(conversation_id=conversation.id, role=role, content=content,
                                  citations=citations, extra_data=metadata)
    db.session.add(message)
    if role == "user" and conversation.title == "New chat":
        conversation.title = content.strip().splitlines()[0][:200]
    db.session.commit()
    return jsonify(message.to_dict()), 201


@conversations_bp.patch("/<int:conversation_id>")
@jwt_required()
def update_conversation(conversation_id):
    conversation = _owned(conversation_id)
    if conversation is None:
        return jsonify({"message": "Conversation not found."}), 404
    payload = request.get_json(silent=True) or {}
    if "title" in payload:
        title = payload["title"]
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
            return jsonify({"message": "Title must contain 1 to 200 characters."}), 400
        conversation.title = title.strip()
    for key in ("is_pinned", "is_archived", "is_locked"):
        if key in payload:
            if not isinstance(payload[key], bool):
                return jsonify({"message": f"{key} must be a boolean."}), 400
            if key == "is_locked" and payload[key] is False:
                return jsonify({"message": "Re-authentication is required to unlock this conversation."}), 409
            setattr(conversation, key, payload[key])
    if conversation.is_locked:
        # A lock must also invalidate any anonymous share link to this chat.
        conversation.share_token = None
    if payload.get("share") is True and conversation.is_locked:
        return jsonify({"message": "Unlock this conversation before sharing it."}), 409
    if payload.get("share") is True:
        conversation.share_token = conversation.share_token or secrets.token_urlsafe(32)
    elif payload.get("share") is False:
        conversation.share_token = None
    db.session.commit()
    return jsonify({**conversation.to_dict(), "share_token": conversation.share_token})


@conversations_bp.post("/<int:conversation_id>/unlock")
@jwt_required()
def unlock_conversation(conversation_id):
    conversation = _owned(conversation_id)
    if conversation is None:
        return jsonify({"message": "Conversation not found."}), 404
    payload = request.get_json(silent=True) or {}
    password = payload.get("password")
    user = db.session.get(User, int(get_jwt_identity()))
    if not isinstance(password, str) or user is None or not user.check_password(password):
        return jsonify({"message": "Password verification failed."}), 401
    conversation.is_locked = False
    db.session.commit()
    return jsonify(conversation.to_dict(include_messages=True))


@conversations_bp.delete("/<int:conversation_id>")
@jwt_required()
def delete_conversation(conversation_id):
    conversation = _owned(conversation_id)
    if conversation is None:
        return jsonify({"message": "Conversation not found."}), 404
    db.session.delete(conversation)
    db.session.commit()
    return jsonify({"status": "success"})


@conversations_bp.get("/shared/<share_token>")
def get_shared_conversation(share_token):
    conversation = Conversation.query.filter_by(share_token=share_token).first()
    if conversation is None or conversation.is_locked:
        return jsonify({"message": "Shared conversation not found."}), 404
    return jsonify(conversation.to_dict(include_messages=True))
