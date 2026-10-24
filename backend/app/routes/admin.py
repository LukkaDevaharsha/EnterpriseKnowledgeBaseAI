"""Admin-only account and shared-knowledge APIs."""

import os
import re
import uuid
from io import BytesIO

import pymupdf
from flask import Blueprint, current_app, jsonify, request, send_file, send_from_directory
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models import AuditEvent, Document, DocumentChunk, User
from app.services.audit import record_admin_action
from app.services.document_workflow import DocumentUploadError, create_document_upload
from app.services.document_processor import extract_document_pages, extract_pdf_outline
from app.services.embedding_service import EmbeddingError
from app.services.ollama_client import OllamaError
from app.services.rag_service import RagValidationError, answer_question, validate_question
from app.services.semantic_search import SearchDatabaseError

admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")
shared_bp = Blueprint("shared_documents", __name__, url_prefix="/api/study/documents")


def _error(message, status=400):
    return jsonify({"status": "error", "message": message}), status


def _actor():
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return None
    user = db.session.get(User, user_id)
    if user is None or not user.is_active or not user.is_verified or user.role != "ADMIN":
        return None
    return user


def _page():
    try:
        page = int(request.args.get("page", "1"))
        per_page = int(request.args.get("per_page", "25"))
    except ValueError:
        return None
    if page < 1 or not 1 <= per_page <= 100:
        return None
    return page, per_page


def _protected_document(document_id, admin=False, user=None):
    query = Document.query.filter_by(id=document_id)
    if not admin:
        query = query.filter(
            (Document.uploaded_by == user.id) | (Document.is_shared.is_(True))
        )
    return query.first()


@admin_bp.get("/stats")
@jwt_required()
def stats():
    actor = _actor()
    if actor is None:
        return _error("Administrator access required.", 403)
    return jsonify({
        "status": "success",
        "stats": {
            "employees": User.query.filter(User.role != "ADMIN").count(),
            "active_accounts": User.query.filter_by(is_active=True).count(),
            "unverified_accounts": User.query.filter_by(is_verified=False).count(),
            "documents": Document.query.count(),
            "shared_documents": Document.query.filter_by(is_shared=True).count(),
            "processed_documents": Document.query.filter_by(status="PROCESSED").count(),
            "failed_documents": Document.query.filter_by(status="PROCESSING_FAILED").count(),
            "chunks": DocumentChunk.query.count(),
            "indexed_chunks": DocumentChunk.query.filter_by(embedding_status="PROCESSED").count(),
        },
    }), 200


@admin_bp.get("/employees")
@jwt_required()
def employees():
    if _actor() is None:
        return _error("Administrator access required.", 403)
    paging = _page()
    if paging is None:
        return _error("Invalid pagination values.", 400)
    page, per_page = paging
    query = User.query.order_by(User.created_at.desc(), User.id.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        "status": "success", "employees": [user.to_dict() for user in pagination.items],
        "pagination": {"page": pagination.page, "per_page": pagination.per_page,
                       "total": pagination.total, "pages": pagination.pages},
    }), 200


@admin_bp.patch("/employees/<int:user_id>")
@jwt_required()
def update_employee(user_id):
    actor = _actor()
    if actor is None:
        return _error("Administrator access required.", 403)
    target = User.query.filter_by(id=user_id).with_for_update().first()
    if target is None:
        return _error("Employee not found.", 404)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not payload:
        return _error("A non-empty JSON object is required.", 400)
    if set(payload) - {"is_active", "role"}:
        return _error("Only account status and role can be changed.", 400)
    if "is_active" in payload and not isinstance(payload["is_active"], bool):
        return _error("is_active must be a boolean.", 400)
    if target.id == actor.id and payload.get("is_active") is False:
        return _error("Administrators cannot deactivate their own account.", 409)
    if "role" in payload and target.id == actor.id:
        return _error("Administrators cannot change their own role.", 409)
    if "role" in payload and payload["role"] == "ADMIN":
        return _error("Employee management cannot grant administrator access.", 403)
    if "role" in payload and payload["role"] != "EMPLOYEE":
        return _error("role must be EMPLOYEE.", 400)

    target_becomes_unusable_admin = (
        target.role == "ADMIN"
        and (("role" in payload and payload["role"] != "ADMIN")
             or (payload.get("is_active") is False and target.is_active))
    )
    if target_becomes_unusable_admin:
        admins = (User.query.filter_by(role="ADMIN", is_active=True, is_verified=True)
                  .order_by(User.id).with_for_update().all())
        if len(admins) <= 1:
            return _error("The last active verified administrator cannot be disabled or demoted.", 409)

    before = {"role": target.role, "is_active": target.is_active}
    if "role" in payload:
        target.role = payload["role"]
    if "is_active" in payload:
        target.is_active = payload["is_active"]
    record_admin_action(actor.id, "employee.update", "user", target.id,
                        {"before": before, "after": {"role": target.role, "is_active": target.is_active}})
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Admin employee update failed.")
        return _error("Employee update failed.", 500)
    return jsonify({"status": "success", "employee": target.to_dict()}), 200


@admin_bp.get("/audit")
@jwt_required()
def audit_events():
    if _actor() is None:
        return _error("Administrator access required.", 403)
    paging = _page()
    if paging is None:
        return _error("Invalid pagination values.", 400)
    page, per_page = paging
    pagination = AuditEvent.query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return jsonify({
        "status": "success",
        "events": [{
            "id": event.id, "actor_user_id": event.actor_user_id,
            "action": event.action, "subject_type": event.subject_type,
            "subject_id": event.subject_id, "details": event.details,
            "created_at": event.created_at.isoformat() if event.created_at else None,
        } for event in pagination.items],
        "pagination": {"page": pagination.page, "per_page": pagination.per_page,
                       "total": pagination.total, "pages": pagination.pages},
    }), 200


@admin_bp.get("/documents")
@jwt_required()
def list_documents():
    if _actor() is None:
        return _error("Administrator access required.", 403)
    paging = _page()
    if paging is None:
        return _error("Invalid pagination values.", 400)
    page, per_page = paging
    # This endpoint supplies the Admin Shared Library. Private employee
    # uploads remain private and must not be presented as library entries.
    pagination = Document.query.filter_by(is_shared=True).order_by(
        Document.created_at.desc(), Document.id.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)
    docs = []
    for doc in pagination.items:
        chunks = DocumentChunk.query.filter_by(document_id=doc.id)
        doc_data = doc.to_dict()
        doc_data["chunk_count"] = chunks.count()
        doc_data["indexed_chunk_count"] = chunks.filter_by(embedding_status="PROCESSED").count()
        docs.append(doc_data)
    return jsonify({"status": "success", "documents": docs,
                    "pagination": {"page": pagination.page, "per_page": pagination.per_page,
                                   "total": pagination.total, "pages": pagination.pages}}), 200


@admin_bp.post("/documents")
@jwt_required()
def upload_shared_document():
    actor = _actor()
    if actor is None:
        return _error("Administrator access required.", 403)
    try:
        doc = create_document_upload(request.files.get("file"), actor,
                                     request.form.get("title", ""), is_shared=True)
    except DocumentUploadError as exc:
        return _error(str(exc), exc.status_code)
    if doc.status != "PROCESSED":
        return jsonify({
            "status": "warning",
            "message": "Document upload was saved, but indexing failed. It is not searchable.",
            "document": doc.to_dict(),
        }), 202
    return jsonify({"status": "success", "message": "Shared document upload completed.",
                    "document": doc.to_dict()}), 201


@admin_bp.get("/documents/<int:document_id>")
@jwt_required()
def inspect_document(document_id):
    if _actor() is None:
        return _error("Administrator access required.", 403)
    document = db.session.get(Document, document_id)
    if document is None:
        return _error("Document not found.", 404)
    data = document.to_dict()
    data["chunks"] = [{
        "chunk_id": chunk.id, "chunk_index": chunk.chunk_index,
        "page_number": chunk.page_number, "embedding_status": chunk.embedding_status,
        "content": chunk.content,
    } for chunk in DocumentChunk.query.filter_by(document_id=document.id).order_by(
        DocumentChunk.chunk_index
    ).all()]
    return jsonify({"status": "success", "document": data}), 200


def _delete_document(document, actor):
    path = os.path.join(current_app.config["DOCUMENT_STORAGE_PATH"], document.stored_filename)
    tombstone = os.path.join(current_app.config["DOCUMENT_STORAGE_PATH"], f".deleting-{uuid.uuid4()}")
    staged = False
    try:
        if os.path.isfile(path):
            os.replace(path, tombstone)
            staged = True
        DocumentChunk.query.filter_by(document_id=document.id).delete(synchronize_session=False)
        record_admin_action(actor.id, "shared_document.delete", "document", document.id,
                            {"title": document.title})
        db.session.delete(document)
        db.session.commit()
    except (OSError, SQLAlchemyError):
        db.session.rollback()
        if staged:
            try:
                os.replace(tombstone, path)
            except OSError:
                current_app.logger.exception("Document delete rollback could not restore the file.")
        current_app.logger.exception("Shared document deletion failed.")
        return _error("Document deletion failed; the document record was retained.", 500)
    if staged:
        try:
            os.remove(tombstone)
        except OSError:
            current_app.logger.exception("Deleted document has a staged file requiring cleanup.")
            return jsonify({"status": "success", "message": "Document deleted; staged file cleanup requires operator attention."}), 200
    return jsonify({"status": "success", "message": "Document deleted successfully."}), 200


@admin_bp.delete("/documents/<int:document_id>")
@jwt_required()
def delete_shared_document(document_id):
    actor = _actor()
    if actor is None:
        return _error("Administrator access required.", 403)
    document = db.session.get(Document, document_id)
    if document is None:
        return _error("Document not found.", 404)
    if not document.is_shared:
        return _error("Only shared documents can be deleted here.", 409)
    return _delete_document(document, actor)


@shared_bp.get("")
@jwt_required()
def study_documents():
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return _error("Invalid authentication token.", 401)
    user = db.session.get(User, user_id)
    if user is None or not user.is_active or not user.is_verified:
        return _error("Active verified user account required.", 403)
    documents = Document.query.filter(
        ((Document.uploaded_by == user.id) | Document.is_shared.is_(True)),
        Document.file_type == "PDF",
    ).order_by(Document.title, Document.id).all()
    return jsonify({"status": "success", "documents": [doc.to_dict() for doc in documents]}), 200


@shared_bp.get("/<int:document_id>/download")
@jwt_required()
def download_study_document(document_id):
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return _error("Invalid authentication token.", 401)
    user = db.session.get(User, user_id)
    if user is None or not user.is_active or not user.is_verified:
        return _error("Active verified user account required.", 403)
    doc = _protected_document(document_id, user=user)
    if doc is None or doc.file_type != "PDF":
        return _error("PDF document not found.", 404)
    path = current_app.config["DOCUMENT_STORAGE_PATH"]
    if not os.path.isfile(os.path.join(path, doc.stored_filename)):
        return _error("Document file is missing from storage.", 404)
    response = send_from_directory(path, doc.stored_filename, as_attachment=False,
                                   download_name=doc.original_filename, mimetype="application/pdf")
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"
    return response


@shared_bp.get("/<int:document_id>/pages")
@jwt_required()
def study_document_pages(document_id):
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return _error("Invalid authentication token.", 401)
    user = db.session.get(User, user_id)
    if user is None or not user.is_active or not user.is_verified:
        return _error("Active verified user account required.", 403)
    document = _protected_document(document_id, user=user)
    if document is None or document.file_type != "PDF":
        return _error("PDF document not found.", 404)
    path = os.path.join(current_app.config["DOCUMENT_STORAGE_PATH"], document.stored_filename)
    if not os.path.isfile(path):
        return _error("Document file is missing from storage.", 404)
    try:
        pages = extract_document_pages(path, "PDF")
        outline = extract_pdf_outline(path)
    except ValueError:
        return _error("PDF text could not be extracted.", 422)
    return jsonify({
        "status": "success", "document_id": document.id,
        "pages": [{"page_number": number, "text": text} for number, text in pages],
        "outline": outline,
    }), 200


@shared_bp.get("/<int:document_id>/pages/<int:page_number>/render")
@jwt_required()
def render_study_document_page(document_id, page_number):
    """Render one authorized PDF page, with optional text search highlights."""
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return _error("Invalid authentication token.", 401)
    user = db.session.get(User, user_id)
    if user is None or not user.is_active or not user.is_verified:
        return _error("Active verified user account required.", 403)

    document = _protected_document(document_id, user=user)
    if document is None or document.file_type != "PDF":
        return _error("PDF document not found.", 404)

    query = request.args.get("query", "").strip()
    if len(query) > 2000:
        return _error("query must not exceed 2000 characters.", 400)
    try:
        scale = float(request.args.get("scale", "1.5"))
    except ValueError:
        return _error("scale must be a number between 0.75 and 3.", 400)
    if not 0.75 <= scale <= 3:
        return _error("scale must be a number between 0.75 and 3.", 400)

    path = os.path.join(current_app.config["DOCUMENT_STORAGE_PATH"], document.stored_filename)
    if not os.path.isfile(path):
        return _error("Document file is missing from storage.", 404)
    try:
        with open(path, "rb") as file:
            pdf_bytes = file.read()
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
            if page_number > pdf.page_count:
                return _error("PDF page not found.", 404)
            page = pdf.load_page(page_number - 1)
            if query:
                matches = page.search_for(query)
                if not matches:
                    terms = list(dict.fromkeys(re.findall(r"[\w]+", query, flags=re.UNICODE)))
                    for term in terms[:20]:
                        if len(term) > 1:
                            matches.extend(page.search_for(term))
                if matches:
                    highlight = page.add_highlight_annot(matches)
                    highlight.set_colors(stroke=(1, 0.78, 0.24))
                    highlight.set_opacity(0.45)
                    highlight.update()
            image = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            image_bytes = image.tobytes("png")
    except (OSError, pymupdf.FileDataError, pymupdf.FileNotFoundError,
            pymupdf.EmptyFileError, RuntimeError, ValueError):
        return _error("PDF page could not be rendered.", 422)

    response = send_file(BytesIO(image_bytes), mimetype="image/png", max_age=0)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"
    return response


@shared_bp.post("/<int:document_id>/ask")
@jwt_required()
def ask_study_document(document_id):
    """Answer against one authorized, indexed study PDF only."""
    try:
        user_id = int(get_jwt_identity())
        user = db.session.get(User, user_id)
    except (TypeError, ValueError):
        return _error("Invalid authentication token.", 401)
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not validate Study PDF question user.")
        return _error("Question answering is temporarily unavailable.", 503)
    if user is None or not user.is_active or not user.is_verified:
        return _error("Active verified user account required.", 403)

    document = _protected_document(document_id, user=user)
    if (document is None or document.file_type != "PDF"
            or document.status != "PROCESSED"):
        return _error("PDF document not found.", 404)
    if not (document.extracted_text or "").strip():
        return _error(
            "This PDF has no extracted text. Upload a text-based PDF or run OCR, then reprocess it.",
            422,
        )

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _error("A JSON object request body is required.", 400)
    question = payload.get("question")
    if not isinstance(question, str):
        return _error("question must be a string.", 400)
    question = question.strip()
    top_k = payload.get("top_k", current_app.config["RAG_DEFAULT_TOP_K"])
    if isinstance(top_k, bool) or not isinstance(top_k, int):
        return _error("top_k must be an integer.", 400)
    if top_k < 1 or top_k > current_app.config["RAG_MAX_TOP_K"]:
        return _error(
            f"top_k must be between 1 and {current_app.config['RAG_MAX_TOP_K']}.",
            400,
        )
    try:
        question = validate_question(question)
        result = answer_question(question, user.id, top_k, document_id=document.id)
    except RagValidationError as exc:
        return _error(str(exc), 400)
    except (EmbeddingError, SearchDatabaseError, OllamaError):
        db.session.rollback()
        current_app.logger.exception("Study PDF question dependency failed.")
        return _error("Question answering is temporarily unavailable.", 503)
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Study PDF question database query failed.")
        return _error("Question answering is temporarily unavailable.", 503)

    return jsonify({"status": "success", "question": question, **result}), 200
