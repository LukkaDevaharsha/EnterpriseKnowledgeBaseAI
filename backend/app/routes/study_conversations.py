"""Persistent, user and document scoped conversations for Study Documents."""
from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app import db
from app.models import Conversation, ConversationMessage, Document, User
from app.services import rag_service

study_conversations_bp = Blueprint("study_conversations", __name__, url_prefix="/api/study/documents")


def _owned_document(document_id):
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return None
    user = db.session.get(User, user_id)
    if user is None or not user.is_active or not user.is_verified or user.role == "ADMIN":
        return None
    return Document.query.filter_by(id=document_id, uploaded_by=user_id, status="PROCESSED").first()


@study_conversations_bp.get("/<int:document_id>/conversations")
@jwt_required()
def list_document_conversations(document_id):
    document = _owned_document(document_id)
    if document is None:
        return jsonify({"message": "Study document not found."}), 404
    rows = Conversation.query.filter_by(user_id=document.uploaded_by, document_id=document.id).order_by(Conversation.updated_at.desc()).all()
    return jsonify({"conversations": [row.to_dict() for row in rows]})


@study_conversations_bp.post("/<int:document_id>/conversations")
@jwt_required()
def create_document_conversation(document_id):
    document = _owned_document(document_id)
    if document is None:
        return jsonify({"message": "Study document not found."}), 404
    conversation = Conversation(user_id=document.uploaded_by, document_id=document.id)
    db.session.add(conversation)
    db.session.commit()
    return jsonify(conversation.to_dict(include_messages=True)), 201


@study_conversations_bp.get("/<int:document_id>/conversations/<int:conversation_id>")
@jwt_required()
def get_document_conversation(document_id, conversation_id):
    document = _owned_document(document_id)
    if document is None:
        return jsonify({"message": "Study document not found."}), 404
    conversation = Conversation.query.filter_by(id=conversation_id, user_id=document.uploaded_by, document_id=document.id).first()
    if conversation is None:
        return jsonify({"message": "Conversation not found."}), 404
    if conversation.is_locked:
        return jsonify({"message": "This conversation is locked."}), 423
    return jsonify(conversation.to_dict(include_messages=True))


@study_conversations_bp.post("/<int:document_id>/chat")
@jwt_required()
def chat_with_document(document_id):
    document = _owned_document(document_id)
    if document is None:
        return jsonify({"message": "Study document not found."}), 404
    user = db.session.get(User, document.uploaded_by)
    if user is None or not user.is_active or not user.is_verified:
        return jsonify({"message": "Active verified user account required."}), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"message": "A JSON object request body is required."}), 400
    try:
        question = rag_service.validate_question(data.get("question"))
    except (TypeError, ValueError) as exc:
        return jsonify({"message": str(exc)}), 400
    if len(question) > 2000:
        return jsonify({"message": "question must not exceed 2000 characters."}), 400
    top_k = data.get("top_k", current_app.config["RAG_DEFAULT_TOP_K"])
    try:
        rag_service.validate_top_k(top_k)
    except (TypeError, ValueError) as exc:
        return jsonify({"message": str(exc)}), 400
    conversation_id = data.get("conversation_id")
    if conversation_id is not None and (isinstance(conversation_id, bool) or not isinstance(conversation_id, int)):
        return jsonify({"message": "conversation_id must be an integer."}), 400
    if conversation_id is None:
        conversation = Conversation(user_id=user.id, document_id=document.id)
        db.session.add(conversation)
        db.session.flush()
    else:
        conversation = Conversation.query.filter_by(id=conversation_id, user_id=user.id, document_id=document.id).first()
        if conversation is None:
            return jsonify({"message": "Conversation not found."}), 404
        if conversation.is_locked or conversation.is_archived:
            return jsonify({"message": "This conversation cannot be updated."}), 423
    previous_messages = conversation.messages[-8:]
    contextual_question = question
    if previous_messages:
        transcript = "\n".join(f"{message.role}: {message.content[:600]}" for message in previous_messages)
        available = max(0, 1950 - len(question))
        contextual_question = f"Conversation context:\n{transcript[-available:]}\n\nFollow-up question: {question}" if available else question
    try:
        result = rag_service.answer_question(contextual_question, user.id, top_k, document_id=document.id)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Study conversation answering failed.")
        return jsonify({"message": "Question answering is temporarily unavailable."}), 503
    user_message = ConversationMessage(conversation_id=conversation.id, role="user", content=question)
    assistant_message = ConversationMessage(conversation_id=conversation.id, role="assistant", content=result.get("answer", ""), citations=result.get("citations", []), extra_data={"insufficient_evidence": result.get("insufficient_evidence", False), "answer_type": result.get("answer_type")})
    db.session.add_all([user_message, assistant_message])
    if conversation.title == "New chat":
        conversation.title = question.splitlines()[0][:200]
    db.session.commit()
    return jsonify({"conversation": conversation.to_dict(), "messages": [user_message.to_dict(), assistant_message.to_dict()], **result})


@study_conversations_bp.delete("/<int:document_id>/conversations/<int:conversation_id>")
@jwt_required()
def delete_document_conversation(document_id, conversation_id):
    document = _owned_document(document_id)
    if document is None:
        return jsonify({"message": "Study document not found."}), 404
    conversation = Conversation.query.filter_by(id=conversation_id, user_id=document.uploaded_by, document_id=document.id).first()
    if conversation is None:
        return jsonify({"message": "Conversation not found."}), 404
    db.session.delete(conversation)
    db.session.commit()
    return jsonify({"status": "success"})
