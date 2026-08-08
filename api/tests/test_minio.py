"""The real MinIO, which the rest of the suite never runs.

`tests/test_storage.py` runs the storage contract against `LocalStorage` and pins
the MinIO error mapping against a stub client. That covers the wiring and the
retry-policy classification, but proves nothing about whether boto3 is being called
correctly, or whether a key with a Thai filename in it survives a real S3 round
trip. That is what this module is for.

Skipped unless `TEST_MINIO_ENDPOINT` is set, so `pytest -q` and CI stay free of a
server — the same shape as `tests/test_postgres.py` and `tests/test_ocr_tesseract.py`:

    TEST_MINIO_ENDPOINT=http://localhost:9000 pytest tests/test_minio.py -q

It writes into its own bucket (`hirelens-test`) and empties it afterwards, so it
must not be pointed at the bucket holding real uploads.
"""

from __future__ import annotations

import contextlib
import os

import pytest

from app.config import Settings, StorageBackend
from app.storage import MinioStorage, StorageError, build_minio_client, build_storage
from tests.storage_contract import StorageContract

TEST_MINIO_ENDPOINT = os.environ.get("TEST_MINIO_ENDPOINT", "")

TEST_BUCKET = "hirelens-test"

pytestmark = pytest.mark.skipif(
    not TEST_MINIO_ENDPOINT,
    reason="Set TEST_MINIO_ENDPOINT to a MinIO/S3 endpoint to run these.",
)


def _settings(**overrides: object) -> Settings:
    fields: dict[str, object] = {
        "storage_backend": StorageBackend.MINIO,
        "minio_endpoint": TEST_MINIO_ENDPOINT,
        "minio_bucket": TEST_BUCKET,
        "jwt_secret": "x" * 40,
    }
    fields.update(overrides)
    return Settings(**fields)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def client():
    """A client, and a throwaway bucket for these tests to live in."""
    client = build_minio_client(_settings())
    # Already there from a previous run is fine — the fixture below empties it.
    with contextlib.suppress(Exception):
        client.create_bucket(Bucket=TEST_BUCKET)
    return client


@pytest.fixture
def storage(client):
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=TEST_BUCKET):
        for entry in page.get("Contents", []):
            client.delete_object(Bucket=TEST_BUCKET, Key=entry["Key"])
    return MinioStorage(client, TEST_BUCKET)


class TestMinioStorage(StorageContract):
    """The same contract `LocalStorage` passes, against a real object store."""


class TestStartupProbe:
    def test_a_bucket_that_exists_builds(self, client):
        assert isinstance(build_storage(_settings()), MinioStorage)

    def test_a_missing_bucket_is_refused(self):
        """The failure this probe exists for: a typo in MINIO_BUCKET should stop the
        process at boot, not surface as a broken upload later."""
        with pytest.raises(StorageError) as caught:
            build_storage(_settings(minio_bucket="hirelens-does-not-exist"))
        assert "hirelens-does-not-exist" in str(caught.value)
