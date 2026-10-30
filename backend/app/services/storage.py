"""Private document storage backends used only by authenticated server code."""

import os
import uuid

from flask import current_app


class StorageError(Exception):
    """Safe storage failure without provider response or credential details."""


def validate_object_key(key):
    """Stored object keys must be canonical UUIDs, never user supplied paths."""
    if not isinstance(key, str):
        raise ValueError("Invalid document storage key.")
    try:
        parsed = uuid.UUID(key)
    except (ValueError, AttributeError, TypeError):
        raise ValueError("Invalid document storage key.") from None
    if str(parsed) != key or "/" in key or "\\" in key:
        raise ValueError("Invalid document storage key.")
    return key


class LocalStorage:
    def __init__(self, root):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def _path(self, key):
        return os.path.join(self.root, validate_object_key(key))

    def upload(self, key, content):
        try:
            with open(self._path(key), "xb") as output:
                output.write(content)
        except OSError as exc:
            raise StorageError("Document storage operation failed.") from exc

    def read(self, key):
        try:
            with open(self._path(key), "rb") as source:
                return source.read()
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise StorageError("Document storage operation failed.") from exc

    def exists(self, key):
        return os.path.isfile(self._path(key))

    def delete(self, key):
        try:
            os.remove(self._path(key))
        except FileNotFoundError:
            return
        except OSError as exc:
            raise StorageError("Document storage operation failed.") from exc


class SupabaseS3Storage:
    def __init__(self, endpoint_url, region, bucket, access_key, secret_key):
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
            ),
        )

    def upload(self, key, content):
        try:
            self.client.put_object(
                Bucket=self.bucket, Key=validate_object_key(key), Body=content
            )
        except self._provider_errors():
            raise StorageError("Document storage operation failed.") from None

    def read(self, key):
        try:
            response = self.client.get_object(
                Bucket=self.bucket, Key=validate_object_key(key)
            )
            body = response["Body"]
            try:
                return body.read()
            finally:
                body.close()
        except self._client_error() as exc:
            if self._status_code(exc) == 404:
                raise FileNotFoundError("Document file is missing from storage.") from None
            raise StorageError("Document storage operation failed.") from None
        except self._provider_errors():
            raise StorageError("Document storage operation failed.") from None

    def exists(self, key):
        try:
            self.client.head_object(
                Bucket=self.bucket, Key=validate_object_key(key)
            )
            return True
        except self._client_error() as exc:
            if self._status_code(exc) == 404:
                return False
            raise StorageError("Document storage operation failed.") from None
        except self._provider_errors():
            raise StorageError("Document storage operation failed.") from None

    def delete(self, key):
        try:
            self.client.delete_object(
                Bucket=self.bucket, Key=validate_object_key(key)
            )
        except self._provider_errors():
            raise StorageError("Document storage operation failed.") from None

    def _client_error(self):
        from botocore.exceptions import ClientError

        return ClientError

    @staticmethod
    def _provider_errors():
        from botocore.exceptions import BotoCoreError, ClientError

        return (BotoCoreError, ClientError)

    @staticmethod
    def _status_code(exc):
        return exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")


def get_storage():
    """Return one storage adapter per Flask app."""
    storage = current_app.extensions.get("document_storage")
    if storage is None:
        if current_app.config["STORAGE_BACKEND"] == "supabase_s3":
            storage = SupabaseS3Storage(
                current_app.config["S3_ENDPOINT_URL"],
                current_app.config["S3_REGION"],
                current_app.config["S3_BUCKET"],
                current_app.config["S3_ACCESS_KEY_ID"],
                current_app.config["S3_SECRET_ACCESS_KEY"],
            )
        else:
            storage = LocalStorage(current_app.config["DOCUMENT_STORAGE_PATH"])
        current_app.extensions["document_storage"] = storage
    return storage
