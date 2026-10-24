"""JWT-protected RAG question-answering endpoint."""

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models import User
from app.services import rag_service
from app.services.embedding_service import EmbeddingError
from app.services.ollama_client import OllamaError
from app.services.rag_service import RagValidationError
from app.services.semantic_search import SearchDatabaseError


ask_bp = Blueprint("ask", __name__, url_prefix="/api")


def _error(message, status_code):
    return jsonify({"status": "error", "message": message}), status_code


@ask_bp.post("/ask")
@jwt_required()
def ask():
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return _error("Invalid authentication token.", 401)

    try:
        user = db.session.get(User, user_id)
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not validate question user.")
        return _error("Question answering is temporarily unavailable.", 503)
    if user is None or not user.is_active:
        return _error("Active user account required.", 403)

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _error("A JSON object request body is required.", 400)
    question = payload.get("question")
    if not isinstance(question, str):
        return _error("question must be a string.", 400)
    question = question.strip()
    if not question:
        return _error("question must not be empty.", 400)
    if len(question) > 2000:
        return _error("question must not exceed 2000 characters.", 400)
    top_k = payload.get("top_k", current_app.config["RAG_DEFAULT_TOP_K"])
    if isinstance(top_k, bool) or not isinstance(top_k, int):
        return _error("top_k must be an integer.", 400)
    if top_k < 1 or top_k > current_app.config["RAG_MAX_TOP_K"]:
        return _error(
            f"top_k must be between 1 and {current_app.config['RAG_MAX_TOP_K']}.",
            400,
        )

    try:
        result = rag_service.answer_question(question, user.id, top_k)
    except RagValidationError as exc:
        # Route validation above normally handles these; keep service callers safe.
        return _error(str(exc), 400)
    except (EmbeddingError, SearchDatabaseError, OllamaError):
        db.session.rollback()
        current_app.logger.exception("Question answering dependency failed.")
        return _error("Question answering is temporarily unavailable.", 503)
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Question answering database query failed.")
        return _error("Question answering is temporarily unavailable.", 503)

    return jsonify({
        "status": "success",
        "question": question,
        **result,
    }), 200
