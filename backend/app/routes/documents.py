import uuid
from io import BytesIO

from flask import (
    Blueprint,
    current_app,
    jsonify,
    request,
    send_file,
)
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.utils import secure_filename

from app import db
from app.models import Document, DocumentChunk, User
from app.services.document_processor import extract_document_pages
from app.services.text_chunker import split_text
from app.services.chunk_embedding_pipeline import process_document_embeddings
from app.services.storage import StorageError, get_storage


documents_bp = Blueprint(
    "documents",
    __name__,
    url_prefix="/api/documents",
)

ALLOWED_EXTENSIONS = {"pdf", "docx", "txt", "md", "pptx", "csv", "xlsx"}
MAX_FILE_SIZE = 10 * 1024 * 1024


def error(message, status_code):
    return jsonify({
        "status": "error",
        "message": message,
    }), status_code


def get_active_user():
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return None

    user = db.session.get(User, user_id)

    if user is None or not user.is_active:
        return None

    return user


def storage_directory():
    """Compatibility seam for tests and the configured storage adapter."""
    return get_storage()


@documents_bp.post("")
@jwt_required()
def upload_document():
    user = get_active_user()

    if user is None:
        return error("Active user account required.", 403)

    uploaded_file = request.files.get("file")

    if uploaded_file is None or not uploaded_file.filename:
        return error("Please select a file to upload.", 400)

    original_filename = secure_filename(uploaded_file.filename)

    if not original_filename:
        return error("Invalid filename.", 400)

    if "." not in original_filename:
        return error("Supported formats are PDF, DOCX, TXT, MD, PPTX, CSV, and XLSX.", 400)

    extension = original_filename.rsplit(".", 1)[-1].lower()

    if extension not in ALLOWED_EXTENSIONS:
        return error("Only PDF and TXT files are allowed.", 400)

    title = request.form.get("title", "").strip()

    if not title:
        title = original_filename

    if len(title) > 255:
        return error("Title must not exceed 255 characters.", 400)

    content = uploaded_file.stream.read(MAX_FILE_SIZE + 1)

    if not content:
        return error("The uploaded file is empty.", 400)

    if len(content) > MAX_FILE_SIZE:
        return error("File size must not exceed 10 MB.", 413)

    file_type = extension.upper()
    if file_type == "PDF" and not content.startswith(b"%PDF-"):
        return error("The uploaded file is not a valid PDF.", 400)
    if file_type in {"TXT", "CSV"}:
        from app.services.document_processor import _decode_text
        try:
            _decode_text(content)
        except ValueError as exc:
            return error(str(exc), 400)
    elif file_type == "MD":
        from app.services.document_processor import _decode_markdown
        try:
            _decode_markdown(content)
        except ValueError as exc:
            return error(str(exc), 400)

    stored_filename = str(uuid.uuid4())
    try:
        storage = storage_directory()
        storage.upload(stored_filename, content)
    except (StorageError, OSError):
        current_app.logger.error("Document storage operation failed.")
        return error("Document storage is unavailable.", 503)

    document = Document(
        title=title,
        original_filename=original_filename,
        stored_filename=stored_filename,
        file_type=file_type,
        file_size=len(content),
        status="UPLOADED",
        extracted_text=None,
        uploaded_by=user.id,
    )

    try:
        document.status = "PROCESSING"

        db.session.add(document)
        db.session.flush()

        try:
            pages = extract_document_pages(content, file_type)
            extracted_text = "\n".join(text for _, text in pages).strip()
            chunks = []
            source_offset = 0
            for page_number, page_text in pages:
                if not page_text:
                    source_offset += 1
                    continue
                for chunk in split_text(page_text):
                    chunk["chunk_index"] = len(chunks)
                    chunk["start_char"] += source_offset
                    chunk["end_char"] += source_offset
                    chunk["page_number"] = page_number
                    chunks.append(chunk)
                source_offset += len(page_text) + 1
            if not chunks:
                raise ValueError("The document contains no usable text chunks.")
            document.extracted_text = extracted_text
            db.session.add_all([
                DocumentChunk(document_id=document.id, **chunk)
                for chunk in chunks
            ])
            db.session.flush()
            document.status = "PROCESSED"

        except ValueError as exc:
            # Preserve the original file and metadata, but do not
            # mark unreadable or text-free documents as processed.
            document.status = "PROCESSING_FAILED"
            current_app.logger.warning(
                "Document %s could not be processed: %s",
                original_filename,
                exc,
            )

        db.session.commit()

    except SQLAlchemyError:
        db.session.rollback()

        try:
            storage.delete(stored_filename)
        except (StorageError, OSError):
            current_app.logger.error("Could not clean up a failed document upload.")

        current_app.logger.exception(
            "Document upload failed."
        )

        return error("Document upload failed.", 500)

    if document.status == "PROCESSED":
        process_document_embeddings(document.id)

    return jsonify({
        "status": "success",
        "message": "Document uploaded successfully.",
        "document": document.to_dict(),
    }), 201


@documents_bp.get("")
@jwt_required()
def list_documents():
    user = get_active_user()

    if user is None:
        return error("Active user account required.", 403)

    try:
        page = int(request.args.get("page", "1"))
        per_page = int(request.args.get("per_page", "10"))
    except ValueError:
        return error("Page values must be integers.", 400)

    if page < 1 or per_page < 1 or per_page > 100:
        return error(
            "Page must be positive and per_page must be between 1 and 100.",
            400,
        )

    pagination = (
        Document.query
        .filter_by(uploaded_by=user.id)
        .order_by(Document.created_at.desc(), Document.id.desc())
        .paginate(
            page=page,
            per_page=per_page,
            error_out=False,
        )
    )

    return jsonify({
        "status": "success",
        "documents": [
            document.to_dict()
            for document in pagination.items
        ],
        "pagination": {
            "page": pagination.page,
            "per_page": pagination.per_page,
            "total": pagination.total,
            "pages": pagination.pages,
        },
    }), 200


@documents_bp.get("/<int:document_id>")
@jwt_required()
def get_document(document_id):
    user = get_active_user()

    if user is None:
        return error("Active user account required.", 403)

    document = Document.query.filter_by(
        id=document_id,
        uploaded_by=user.id,
    ).first()

    if document is None:
        return error("Document not found.", 404)

    return jsonify({
        "status": "success",
        "document": document.to_dict(),
    }), 200


@documents_bp.get("/<int:document_id>/download")
@jwt_required()
def download_document(document_id):
    user = get_active_user()

    if user is None:
        return error("Active user account required.", 403)

    document = Document.query.filter_by(
        id=document_id,
        uploaded_by=user.id,
    ).first()

    if document is None:
        return error("Document not found.", 404)

    storage = storage_directory()
    try:
        content = storage.read(document.stored_filename)
    except FileNotFoundError:
        return error("Document file is missing from storage.", 404)
    except StorageError:
        return error("Document storage is unavailable.", 503)

    response = send_file(
        BytesIO(content),
        as_attachment=True,
        download_name=document.original_filename,
    )

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"

    return response


@documents_bp.delete("/<int:document_id>")
@jwt_required()
def delete_document(document_id):
    user = get_active_user()

    if user is None:
        return error("Active user account required.", 403)

    document = Document.query.filter_by(
        id=document_id,
        uploaded_by=user.id,
    ).first()

    if document is None:
        return error("Document not found.", 404)

    try:
        DocumentChunk.query.filter_by(document_id=document.id).delete(
            synchronize_session=False
        )
        db.session.delete(document)
        db.session.commit()

    except SQLAlchemyError:
        db.session.rollback()

        current_app.logger.exception(
            "Document deletion failed."
        )

        return error("Document deletion failed.", 500)

    try:
        storage_directory().delete(document.stored_filename)
    except (StorageError, OSError):
        current_app.logger.exception(
            "Database record deleted, but the stored file "
            "could not be removed."
        )

        return jsonify({
            "status": "success",
            "message": (
                "Document record deleted, but its stored file "
                "could not be removed. Server cleanup is required."
            ),
        }), 200

    return jsonify({
        "status": "success",
        "message": "Document deleted successfully.",
    }), 200
