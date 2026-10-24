"""Tests for document upload and management APIs."""

import os
from io import BytesIO

import pytest
from flask_jwt_extended import create_access_token

from app import db
from app.models import Document, DocumentChunk, User


MAX_FILE_SIZE = 10 * 1024 * 1024


@pytest.fixture
def user_token(app):
    """Create a test user and return an authorization header."""

    with app.app_context():
        user = User(
            name="Test User",
            email="documents.user@example.com",
            employee_id="DOC001",
            department="Engineering",
            role="EMPLOYEE",
            is_active=True,
        )
        user.set_password("StrongPassword123")

        db.session.add(user)
        db.session.commit()

        token = create_access_token(identity=str(user.id))

        return {
            "Authorization": f"Bearer {token}"
        }


@pytest.fixture
def second_user_token(app):
    """Create a different user for ownership tests."""

    with app.app_context():
        user = User(
            name="Second User",
            email="second.user@example.com",
            employee_id="DOC002",
            department="Engineering",
            role="EMPLOYEE",
            is_active=True,
        )
        user.set_password("StrongPassword123")

        db.session.add(user)
        db.session.commit()

        token = create_access_token(identity=str(user.id))

        return {
            "Authorization": f"Bearer {token}"
        }


def upload_txt(client, headers, filename="notes.txt", content=b"Knowledge base test"):
    return client.post(
        "/api/documents",
        headers=headers,
        data={
            "file": (BytesIO(content), filename),
        },
        content_type="multipart/form-data",
    )


def test_list_documents_requires_authentication(client):
    response = client.get("/api/documents")

    assert response.status_code == 401


def test_upload_txt_document(client, app, user_token):
    response = upload_txt(client, user_token)

    assert response.status_code == 201

    body = response.get_json()

    assert body["status"] == "success"
    assert body["document"]["title"] == "notes.txt"
    assert body["document"]["original_filename"] == "notes.txt"
    assert body["document"]["file_type"] == "TXT"
    assert body["document"]["file_size"] == len(
        b"Knowledge base test"
    )
    assert "stored_filename" not in body["document"]

    with app.app_context():
        document = db.session.get(
            Document,
            body["document"]["id"],
        )

        assert document is not None

        stored_path = os.path.join(
            app.config["DOCUMENT_STORAGE_PATH"],
            document.stored_filename,
        )

        assert os.path.isfile(stored_path)

        with open(stored_path, "rb") as file:
            assert file.read() == b"Knowledge base test"


def test_upload_pdf_document(client, user_token):
    pdf_content = (
        b"%PDF-1.4\n"
        b"Test PDF content\n"
        b"%%EOF"
    )

    response = client.post(
        "/api/documents",
        headers=user_token,
        data={
            "file": (BytesIO(pdf_content), "guide.pdf"),
            "title": "Employee Guide",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 201

    document = response.get_json()["document"]

    assert document["title"] == "Employee Guide"
    assert document["file_type"] == "PDF"


def test_upload_requires_file(client, user_token):
    response = client.post(
        "/api/documents",
        headers=user_token,
        data={},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400


def test_upload_rejects_unsupported_extension(client, user_token):
    response = client.post(
        "/api/documents",
        headers=user_token,
        data={
            "file": (
                BytesIO(b"some content"),
                "program.exe",
            ),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400


def test_upload_rejects_empty_file(client, user_token):
    response = upload_txt(
        client,
        user_token,
        content=b"",
    )

    assert response.status_code == 400


def test_upload_returns_safe_error_when_storage_is_unavailable(
    client, user_token, monkeypatch
):
    from app.routes import documents as document_routes

    def unavailable_storage():
        raise OSError("private storage path")

    monkeypatch.setattr(document_routes, "storage_directory", unavailable_storage)
    response = upload_txt(client, user_token)

    assert response.status_code == 503
    assert response.get_json() == {
        "status": "error",
        "message": "Document storage is unavailable.",
    }
    assert "private storage path" not in response.get_data(as_text=True)


def test_upload_returns_safe_error_when_storage_write_fails(
    client, user_token, monkeypatch
):
    def fail_write(*args, **kwargs):
        raise OSError("private storage path")

    monkeypatch.setattr("builtins.open", fail_write)
    response = upload_txt(client, user_token)

    assert response.status_code == 503
    assert response.get_json()["message"] == "Document storage is unavailable."
    assert "private storage path" not in response.get_data(as_text=True)


def test_upload_rejects_invalid_pdf(client, user_token):
    response = client.post(
        "/api/documents",
        headers=user_token,
        data={
            "file": (
                BytesIO(b"This is not a PDF"),
                "invalid.pdf",
            ),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400


def test_upload_rejects_binary_txt(client, user_token):
    response = upload_txt(
        client,
        user_token,
        content=b"invalid\x00text",
    )

    assert response.status_code == 400


def test_upload_rejects_file_larger_than_10_mb(
    client,
    user_token,
):
    large_content = b"a" * (MAX_FILE_SIZE + 1)

    response = upload_txt(
        client,
        user_token,
        content=large_content,
    )

    assert response.status_code == 413


def test_list_documents_returns_uploaded_documents(
    client,
    user_token,
):
    upload_txt(
        client,
        user_token,
        filename="first.txt",
        content=b"First document",
    )

    upload_txt(
        client,
        user_token,
        filename="second.txt",
        content=b"Second document",
    )

    response = client.get(
        "/api/documents",
        headers=user_token,
    )

    assert response.status_code == 200

    body = response.get_json()

    assert body["status"] == "success"
    assert len(body["documents"]) == 2
    assert body["pagination"]["total"] == 2
    assert body["pagination"]["page"] == 1


def test_list_documents_supports_pagination(
    client,
    user_token,
):
    for index in range(3):
        upload_txt(
            client,
            user_token,
            filename=f"document{index}.txt",
            content=f"Document {index}".encode(),
        )

    response = client.get(
        "/api/documents?page=1&per_page=2",
        headers=user_token,
    )

    assert response.status_code == 200

    body = response.get_json()

    assert len(body["documents"]) == 2
    assert body["pagination"]["total"] == 3
    assert body["pagination"]["pages"] == 2


@pytest.mark.parametrize(
    "query",
    [
        "?page=0",
        "?page=abc",
        "?per_page=0",
        "?per_page=101",
    ],
)
def test_list_documents_rejects_invalid_pagination(
    client,
    user_token,
    query,
):
    response = client.get(
        f"/api/documents{query}",
        headers=user_token,
    )

    assert response.status_code == 400


def test_get_document_details(client, user_token):
    upload_response = upload_txt(client, user_token)

    document_id = upload_response.get_json()["document"]["id"]

    response = client.get(
        f"/api/documents/{document_id}",
        headers=user_token,
    )

    assert response.status_code == 200
    assert response.get_json()["document"]["id"] == document_id


def test_user_cannot_view_another_users_document(
    client,
    user_token,
    second_user_token,
):
    upload_response = upload_txt(client, user_token)

    document_id = upload_response.get_json()["document"]["id"]

    response = client.get(
        f"/api/documents/{document_id}",
        headers=second_user_token,
    )

    assert response.status_code == 404


def test_user_cannot_download_another_users_document(
    client,
    user_token,
    second_user_token,
):
    upload_response = upload_txt(client, user_token)

    document_id = upload_response.get_json()["document"]["id"]

    response = client.get(
        f"/api/documents/{document_id}/download",
        headers=second_user_token,
    )

    assert response.status_code == 404


def test_download_document(client, user_token):
    content = b"Download this document"

    upload_response = upload_txt(
        client,
        user_token,
        filename="download.txt",
        content=content,
    )

    document_id = upload_response.get_json()["document"]["id"]

    response = client.get(
        f"/api/documents/{document_id}/download",
        headers=user_token,
    )

    assert response.status_code == 200
    assert response.data == content
    assert "attachment" in response.headers.get(
        "Content-Disposition",
        "",
    )


def test_delete_document_removes_record_and_file(
    client,
    app,
    user_token,
):
    upload_response = upload_txt(client, user_token)

    document_id = upload_response.get_json()["document"]["id"]

    with app.app_context():
        document = db.session.get(Document, document_id)
        stored_path = os.path.join(
            app.config["DOCUMENT_STORAGE_PATH"],
            document.stored_filename,
        )

        assert os.path.isfile(stored_path)

    response = client.delete(
        f"/api/documents/{document_id}",
        headers=user_token,
    )

    assert response.status_code == 200

    with app.app_context():
        assert db.session.get(Document, document_id) is None
        assert DocumentChunk.query.filter_by(document_id=document_id).count() == 0
        assert not os.path.exists(stored_path)


def test_user_cannot_delete_another_users_document(
    client,
    user_token,
    second_user_token,
):
    upload_response = upload_txt(client, user_token)

    document_id = upload_response.get_json()["document"]["id"]

    response = client.delete(
        f"/api/documents/{document_id}",
        headers=second_user_token,
    )

    assert response.status_code == 404


def test_get_nonexistent_document_returns_404(
    client,
    user_token,
):
    response = client.get(
        "/api/documents/999999",
        headers=user_token,
    )

    assert response.status_code == 404


def test_upload_rejects_title_longer_than_255_characters(
    client,
    user_token,
):
    response = client.post(
        "/api/documents",
        headers=user_token,
        data={
            "title": "T" * 256,
            "file": (
                BytesIO(b"Test content"),
                "notes.txt",
            ),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
