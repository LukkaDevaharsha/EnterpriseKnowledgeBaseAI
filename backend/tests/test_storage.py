from io import BytesIO
import uuid

import pytest
from botocore.exceptions import ClientError

from app import create_app, db
from app.models import User
from app.services.storage import (
    LocalStorage,
    SupabaseS3Storage,
    validate_object_key,
)


class FakeS3Client:
    def __init__(self):
        self.calls = []
        self.objects = {}

    def put_object(self, **kwargs):
        self.calls.append(("put_object", kwargs))
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs["Body"]

    def get_object(self, **kwargs):
        self.calls.append(("get_object", kwargs))
        key = (kwargs["Bucket"], kwargs["Key"])
        if key not in self.objects:
            raise ClientError({"ResponseMetadata": {"HTTPStatusCode": 404}}, "GetObject")
        return {"Body": BytesIO(self.objects[key])}

    def head_object(self, **kwargs):
        self.calls.append(("head_object", kwargs))
        key = (kwargs["Bucket"], kwargs["Key"])
        if key not in self.objects:
            raise ClientError({"ResponseMetadata": {"HTTPStatusCode": 404}}, "HeadObject")

    def delete_object(self, **kwargs):
        self.calls.append(("delete_object", kwargs))
        self.objects.pop((kwargs["Bucket"], kwargs["Key"]), None)


def _configure_app(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("JWT_SECRET_KEY", "storage-test-key")
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("DOCUMENT_STORAGE_PATH", raising=False)


def test_local_storage_is_default(monkeypatch, tmp_path):
    _configure_app(monkeypatch)
    app = create_app({"TESTING": True, "DOCUMENT_STORAGE_PATH": str(tmp_path / "local")})

    assert app.config["STORAGE_BACKEND"] == "local"
    assert isinstance(app.extensions.get("document_storage"), type(None))


def test_supabase_configuration_does_not_require_local_path(monkeypatch):
    _configure_app(monkeypatch)
    app = create_app({
        "TESTING": True,
        "STORAGE_BACKEND": "supabase_s3",
        "S3_ACCESS_KEY_ID": "test-access-key",
        "S3_SECRET_ACCESS_KEY": "test-secret-key",
    })

    assert app.config["STORAGE_BACKEND"] == "supabase_s3"
    assert app.config["S3_ENDPOINT_URL"] == (
        "https://ixkkqeyzopkbdcfnzwye.storage.supabase.co/storage/v1/s3"
    )
    assert app.config["S3_REGION"] == "ap-southeast-1"
    assert app.config["S3_BUCKET"] == "enterprise-knowledge-base-docs"


@pytest.mark.parametrize(
    "overrides",
    [
        {"STORAGE_BACKEND": "unknown"},
        {"STORAGE_BACKEND": "supabase_s3"},
        {"STORAGE_BACKEND": "supabase_s3", "S3_ACCESS_KEY_ID": "x",
         "S3_SECRET_ACCESS_KEY": "y", "S3_ENDPOINT_URL": "http://unsafe.example"},
    ],
)
def test_invalid_storage_configuration_is_rejected(monkeypatch, overrides):
    _configure_app(monkeypatch)
    with pytest.raises(RuntimeError, match="STORAGE_BACKEND|S3"):
        create_app({"TESTING": True, **overrides})


def test_s3_operations_use_private_bucket_and_uuid_key(monkeypatch):
    import boto3

    fake = FakeS3Client()
    client_options = {}
    monkeypatch.setattr(
        boto3, "client",
        lambda service, **kwargs: client_options.update(service=service, **kwargs) or fake,
    )
    storage = SupabaseS3Storage(
        "https://storage.example/s3", "ap-southeast-1", "private-bucket",
        "test-access", "test-secret",
    )
    key = str(uuid.uuid4())

    storage.upload(key, b"private document")
    assert storage.exists(key) is True
    assert storage.read(key) == b"private document"
    storage.delete(key)
    assert storage.exists(key) is False
    assert [name for name, _ in fake.calls] == [
        "put_object", "head_object", "get_object", "delete_object", "head_object"
    ]
    assert all(call["Bucket"] == "private-bucket" for _, call in fake.calls)
    assert all(call["Key"] == key for _, call in fake.calls)
    assert client_options["service"] == "s3"
    assert client_options["endpoint_url"] == "https://storage.example/s3"
    assert client_options["region_name"] == "ap-southeast-1"
    assert client_options["config"].signature_version == "s3v4"
    assert client_options["config"].s3["addressing_style"] == "path"


def test_s3_missing_object_and_invalid_keys_are_safe(monkeypatch):
    import boto3

    fake = FakeS3Client()
    monkeypatch.setattr(boto3, "client", lambda *_args, **_kwargs: fake)
    storage = SupabaseS3Storage("https://storage.example", "region", "bucket", "a", "b")

    assert storage.exists(str(uuid.uuid4())) is False
    with pytest.raises(FileNotFoundError):
        storage.read(str(uuid.uuid4()))
    with pytest.raises(ValueError):
        validate_object_key("../private.txt")
    with pytest.raises(ValueError):
        storage.delete("../private.txt")


def test_local_storage_round_trip_and_missing_object(tmp_path):
    storage = LocalStorage(str(tmp_path))
    key = str(uuid.uuid4())

    storage.upload(key, b"local")
    assert storage.exists(key)
    assert storage.read(key) == b"local"
    storage.delete(key)
    assert not storage.exists(key)
    with pytest.raises(FileNotFoundError):
        storage.read(key)


def test_document_download_and_study_preview_use_storage_after_authorization(
    client, app, monkeypatch
):
    import pymupdf
    from flask_jwt_extended import create_access_token

    class MemoryStorage:
        def __init__(self):
            self.objects = {}
            self.reads = []

        def upload(self, key, content):
            self.objects[key] = content

        def read(self, key):
            self.reads.append(key)
            if key not in self.objects:
                raise FileNotFoundError
            return self.objects[key]

        def exists(self, key):
            return key in self.objects

        def delete(self, key):
            self.objects.pop(key, None)

    with app.app_context():
        owner = User(
            name="Storage Owner", email="storage-owner@example.test",
            employee_id="STORAGE-OWNER", department="Research", role="EMPLOYEE",
            is_active=True, is_verified=True, password_hash="test-hash",
        )
        other = User(
            name="Storage Other", email="storage-other@example.test",
            employee_id="STORAGE-OTHER", department="Research", role="EMPLOYEE",
            is_active=True, is_verified=True, password_hash="test-hash",
        )
        db.session.add_all([owner, other])
        db.session.commit()
        owner_headers = {"Authorization": f"Bearer {create_access_token(identity=str(owner.id))}"}
        other_headers = {"Authorization": f"Bearer {create_access_token(identity=str(other.id))}"}

    storage = MemoryStorage()
    monkeypatch.setitem(app.extensions, "document_storage", storage)
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Private preview content")
    pdf_bytes = pdf.tobytes()
    pdf.close()

    uploaded = client.post(
        "/api/documents", headers=owner_headers,
        data={"file": (BytesIO(pdf_bytes), "private.pdf")},
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 201
    document_id = uploaded.get_json()["document"]["id"]

    before_unauthorized = len(storage.reads)
    denied = client.get(f"/api/documents/{document_id}/download", headers=other_headers)
    assert denied.status_code == 404
    assert len(storage.reads) == before_unauthorized

    download = client.get(f"/api/documents/{document_id}/download", headers=owner_headers)
    assert download.status_code == 200
    assert download.data == pdf_bytes
    pages = client.get(f"/api/study/documents/{document_id}/pages", headers=owner_headers)
    assert pages.status_code == 200
    assert "Private preview content" in pages.get_json()["pages"][0]["text"]
    rendered = client.get(
        f"/api/study/documents/{document_id}/pages/1/render", headers=owner_headers
    )
    assert rendered.status_code == 200
    assert rendered.mimetype == "image/png"
