"""Shared validated upload/index workflow used by employee and admin routes."""

import uuid

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.utils import secure_filename

from app import db
from app.models import AuditEvent, Document, DocumentChunk
from app.services.chunk_embedding_pipeline import process_document_embeddings
from app.services.document_processor import extract_document_pages
from app.services.text_chunker import split_text
from app.services.storage import StorageError, get_storage

ALLOWED_EXTENSIONS = {"pdf", "docx", "txt", "md", "pptx", "csv", "xlsx"}
MAX_FILE_SIZE = 10 * 1024 * 1024


class DocumentUploadError(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code


def create_document_upload(uploaded_file, user, title="", is_shared=False):
    if uploaded_file is None or not uploaded_file.filename:
        raise DocumentUploadError("Please select a file to upload.", 400)
    filename = secure_filename(uploaded_file.filename)
    if not filename:
        raise DocumentUploadError("Invalid filename.", 400)
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise DocumentUploadError("Supported formats are PDF, DOCX, TXT, MD, PPTX, CSV, and XLSX.", 400)
    title = (title or "").strip() or filename
    if len(title) > 255:
        raise DocumentUploadError("Title must not exceed 255 characters.", 400)
    content = uploaded_file.stream.read(MAX_FILE_SIZE + 1)
    if not content:
        raise DocumentUploadError("The uploaded file is empty.", 400)
    if len(content) > MAX_FILE_SIZE:
        raise DocumentUploadError("File size must not exceed 10 MB.", 413)
    file_type = extension.upper()
    # Validate the content directly; temporary filesystem copies are unnecessary.
    try:
        pages = extract_document_pages(content, file_type)
    except ValueError as exc:
        raise DocumentUploadError(str(exc), 400) from exc

    stored_filename = str(uuid.uuid4())
    document = Document(
        title=title, original_filename=filename, stored_filename=stored_filename,
        file_type=file_type, file_size=len(content), status="PROCESSING",
        uploaded_by=user.id, is_shared=bool(is_shared),
    )
    try:
        get_storage().upload(stored_filename, content)
    except (StorageError, OSError) as exc:
        raise DocumentUploadError("Document storage is unavailable.", 503) from exc

    try:
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
        db.session.add(document)
        db.session.flush()
        db.session.add_all([
            DocumentChunk(document_id=document.id, **chunk) for chunk in chunks
        ])
        db.session.flush()
        if is_shared:
            db.session.add(AuditEvent(
                actor_user_id=user.id, action="shared_document.upload",
                subject_type="document", subject_id=str(document.id),
                details={"title": title, "file_type": file_type},
            ))
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        document.status = "PROCESSING_FAILED"
        document.processing_error = "Document text could not be extracted."
        try:
            db.session.add(document)
            if is_shared:
                db.session.add(AuditEvent(
                    actor_user_id=user.id, action="shared_document.processing_failed",
                    subject_type="document", subject_id=None,
                    details={"title": title, "file_type": file_type},
                ))
            db.session.commit()
        except SQLAlchemyError as db_error:
            db.session.rollback()
            try:
                get_storage().delete(stored_filename)
            except (StorageError, OSError):
                current_app.logger.error("Failed upload cleanup requires operator attention.")
            raise DocumentUploadError("Document processing failed.", 500) from db_error
    except (OSError, SQLAlchemyError) as exc:
        db.session.rollback()
        try:
            get_storage().delete(stored_filename)
        except (StorageError, OSError):
            current_app.logger.error("Failed upload cleanup requires operator attention.")
        if isinstance(exc, (StorageError, OSError)):
            raise DocumentUploadError("Document storage is unavailable.", 503) from exc
        current_app.logger.exception("Document upload persistence failed.")
        raise DocumentUploadError("Document upload failed.", 500) from exc

    if document.status == "PROCESSING":
        if process_document_embeddings(document.id):
            document.status = "PROCESSED"
            document.processing_error = None
        else:
            document.status = "PROCESSING_FAILED"
            document.processing_error = "Document indexing failed."
        try:
            db.session.commit()
        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception("Document indexing status could not be saved.")
            raise DocumentUploadError("Document indexing failed.", 500) from exc
    return document
