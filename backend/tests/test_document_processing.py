"""Tests for document text extraction and processing status."""

from io import BytesIO

import pymupdf
import pytest
from sqlalchemy.exc import SQLAlchemyError
from flask_jwt_extended import create_access_token

from app import db
from app.models import Document, DocumentChunk, User


@pytest.fixture
def processing_user_token(app):
    with app.app_context():
        user = User(
            name="Processing User",
            email="processing.user@example.com",
            employee_id="PROC001",
            department="Engineering",
            role="EMPLOYEE",
            is_active=True,
        )
        user.set_password("StrongPassword123")

        db.session.add(user)
        db.session.commit()

        token = create_access_token(identity=str(user.id))

        return {"Authorization": f"Bearer {token}"}


def upload_file(client, headers, filename, content, title=None):
    data = {
        "file": (BytesIO(content), filename),
    }

    if title is not None:
        data["title"] = title

    return client.post(
        "/api/documents",
        headers=headers,
        data=data,
        content_type="multipart/form-data",
    )


def create_pdf(text):
    """Create a valid PDF containing selectable text."""
    pdf = pymupdf.open()

    page = pdf.new_page()
    page.insert_text(
        (72, 72),
        text,
        fontsize=12,
    )

    content = pdf.tobytes()
    pdf.close()

    return content


def test_txt_upload_extracts_text(
    client,
    app,
    processing_user_token,
):
    content = b"Enterprise knowledge base text extraction test."

    response = upload_file(
        client,
        processing_user_token,
        "knowledge.txt",
        content,
    )

    assert response.status_code == 201

    document_id = response.get_json()["document"]["id"]

    with app.app_context():
        document = db.session.get(Document, document_id)

        assert document is not None
        assert document.status == "PROCESSED"
        assert document.extracted_text == content.decode("utf-8")
        chunks = DocumentChunk.query.filter_by(document_id=document_id).all()
        assert len(chunks) == 1
        assert chunks[0].content == document.extracted_text
        assert chunks[0].start_char == 0
        assert chunks[0].end_char == len(document.extracted_text)
        assert chunks[0].embedding_status == "PROCESSED"
        assert chunks[0].embedding_model == "sentence-transformers/all-MiniLM-L6-v2"
        assert len(chunks[0].embedding) == 384


def test_pdf_upload_extracts_text(
    client,
    app,
    processing_user_token,
):
    expected_text = "Enterprise PDF extraction test."
    pdf_content = create_pdf(expected_text)

    response = upload_file(
        client,
        processing_user_token,
        "guide.pdf",
        pdf_content,
    )

    assert response.status_code == 201

    document_id = response.get_json()["document"]["id"]

    with app.app_context():
        document = db.session.get(Document, document_id)

        assert document is not None
        assert document.status == "PROCESSED"
        assert expected_text in document.extracted_text
        chunks = DocumentChunk.query.filter_by(document_id=document_id).all()
        assert chunks
        assert all(chunk.document_id == document.id for chunk in chunks)
        assert all(
            document.extracted_text[chunk.start_char:chunk.end_char] == chunk.content
            for chunk in chunks
        )


def test_unreadable_pdf_is_not_marked_processed(
    client,
    app,
    processing_user_token,
):
    invalid_pdf = b"%PDF-1.4\nThis is not a valid PDF document."

    response = upload_file(
        client,
        processing_user_token,
        "unreadable.pdf",
        invalid_pdf,
    )

    assert response.status_code == 201

    document_id = response.get_json()["document"]["id"]

    with app.app_context():
        document = db.session.get(Document, document_id)

        assert document is not None
        assert document.status == "PROCESSING_FAILED"
        assert document.extracted_text is None
        assert DocumentChunk.query.filter_by(document_id=document_id).count() == 0


def test_text_free_document_is_not_processed(client, app, processing_user_token):
    response = upload_file(client, processing_user_token, "blank.txt", b" \n\t ")
    assert response.status_code == 201
    document_id = response.get_json()["document"]["id"]
    with app.app_context():
        document = db.session.get(Document, document_id)
        assert document.status == "PROCESSING_FAILED"
        assert DocumentChunk.query.filter_by(document_id=document_id).count() == 0


def test_chunk_persistence_failure_rolls_back_upload(client, app, processing_user_token, monkeypatch):
    from app.routes import documents as document_routes

    original_flush = document_routes.db.session.flush
    failed = False

    def fail_after_chunk_insert(*args, **kwargs):
        nonlocal failed
        if not failed and DocumentChunk.query.count():
            failed = True
            raise SQLAlchemyError("simulated persistence failure")
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(document_routes.db.session, "flush", fail_after_chunk_insert)
    response = upload_file(client, processing_user_token, "atomic.txt", b"atomic text")
    assert response.status_code == 500
    with app.app_context():
        assert Document.query.filter_by(original_filename="atomic.txt").count() == 0
        assert DocumentChunk.query.count() == 0


def test_chunk_indices_and_order_match_source(client, app, processing_user_token):
    text = " ".join(f"section{i}" for i in range(250))
    response = upload_file(client, processing_user_token, "long.txt", text.encode())
    assert response.status_code == 201
    document_id = response.get_json()["document"]["id"]
    with app.app_context():
        chunks = DocumentChunk.query.filter_by(document_id=document_id).order_by(
            DocumentChunk.chunk_index
        ).all()
        assert len(chunks) > 1
        assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
        assert all(text[chunk.start_char:chunk.end_char] == chunk.content for chunk in chunks)
        assert all(chunk.embedding_status == "PROCESSED" for chunk in chunks)
        assert all(len(chunk.embedding) == 384 for chunk in chunks)


def test_embedding_failure_keeps_processed_document_and_saved_chunks(
    client, app, processing_user_token, monkeypatch
):
    from app.routes import documents as document_routes

    monkeypatch.setattr(
        document_routes,
        "process_document_embeddings",
        lambda document_id: False,
    )
    response = upload_file(
        client, processing_user_token, "embedding-error.txt", b"saved chunks survive"
    )
    assert response.status_code == 201
    document_id = response.get_json()["document"]["id"]
    with app.app_context():
        document = db.session.get(Document, document_id)
        chunks = DocumentChunk.query.filter_by(document_id=document_id).all()
        assert document.status == "PROCESSED"
        assert document.extracted_text == "saved chunks survive"
        assert len(chunks) == 1


def test_document_metadata_does_not_return_extracted_text(
    client,
    processing_user_token,
):
    response = upload_file(
        client,
        processing_user_token,
        "private.txt",
        b"Internal company information.",
    )

    assert response.status_code == 201

    document = response.get_json()["document"]

    assert document["status"] == "PROCESSED"
    assert "extracted_text" not in document
