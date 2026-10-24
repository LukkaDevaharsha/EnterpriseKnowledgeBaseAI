"""Authenticated semantic search API."""

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models import User
from app.services.embedding_service import EmbeddingError
from app.services.semantic_search import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MAX_QUERY_LENGTH,
    SearchDatabaseError,
    search_chunks,
)


search_bp = Blueprint("search", __name__, url_prefix="/api")


def _error(message, status_code):
    return jsonify({"status": "error", "message": message}), status_code


@search_bp.post("/search")
@jwt_required()
def semantic_search():
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return _error("Invalid authentication token.", 401)

    try:
        user = db.session.get(User, user_id)
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not validate search user.")
        return _error("Search is temporarily unavailable.", 503)
    if user is None or not user.is_active:
        return _error("Active user account required.", 403)

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _error("A JSON object request body is required.", 400)
    query = payload.get("query")
    if not isinstance(query, str):
        return _error("query must be a string.", 400)
    query = query.strip()
    if not query:
        return _error("query must not be empty.", 400)
    if len(query) > MAX_QUERY_LENGTH:
        return _error(
            f"query must not exceed {MAX_QUERY_LENGTH} characters.", 400
        )

    limit = payload.get("limit", DEFAULT_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int):
        return _error("limit must be an integer.", 400)
    if limit < 1 or limit > MAX_LIMIT:
        return _error(f"limit must be between 1 and {MAX_LIMIT}.", 400)

    try:
        results = search_chunks(query, user.id, limit)
    except EmbeddingError:
        db.session.rollback()
        current_app.logger.exception("Query embedding generation failed.")
        return _error("Search is temporarily unavailable.", 503)
    except SearchDatabaseError:
        db.session.rollback()
        current_app.logger.exception("Semantic search database query failed.")
        return _error("Search is temporarily unavailable.", 503)
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Semantic search database query failed.")
        return _error("Search is temporarily unavailable.", 503)

    return jsonify({
        "status": "success",
        "query": query,
        "results": results,
        "count": len(results),
    }), 200
