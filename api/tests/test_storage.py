"""Storage: the shared contract on `LocalStorage`, plus the MinIO error mapping.

The error mapping is tested here rather than in the opt-in MinIO module on purpose.
It decides whether a failure is *permanent* or *transient* — `jobs.is_retryable`
gives up on `ObjectNotFoundError` and retries everything else — and a rule that
important must be pinned on every run, not only on a machine that happens to have
MinIO up.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from app.config import Settings, StorageBackend
from app.storage import (
    LocalStorage,
    MinioStorage,
    ObjectNotFoundError,
    StorageError,
    build_storage,
    build_storage_key,
    content_hash,
)
from tests.storage_contract import StorageContract


class TestLocalStorage(StorageContract):
    @pytest.fixture
    def storage(self, tmp_path):
        return LocalStorage(tmp_path)

    async def test_refuses_to_escape_its_root(self, tmp_path):
        storage = LocalStorage(tmp_path / "root")
        with pytest.raises(StorageError):
            await storage.put("../../escaped.bin", b"nope")


class TestStorageKeys:
    def test_the_same_bytes_give_the_same_key(self):
        digest = content_hash(b"%PDF-1.4 resume")
        first = build_storage_key(candidate_id="c1", digest=digest, filename="cv.pdf")
        second = build_storage_key(candidate_id="c1", digest=digest, filename="CV.PDF")
        assert first == second

    def test_two_candidates_never_share_a_key(self):
        digest = content_hash(b"%PDF-1.4 resume")
        assert build_storage_key(
            candidate_id="c1", digest=digest, filename="cv.pdf"
        ) != build_storage_key(candidate_id="c2", digest=digest, filename="cv.pdf")


def _client_error(code: str, status: int) -> ClientError:
    return ClientError(
        {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}},
        "GetObject",
    )


class _FailingClient:
    """A client that raises whatever it was built with, for every operation."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    def _raise(self, **_kwargs: object) -> None:
        raise self._error

    get_object = put_object = delete_object = head_object = head_bucket = _raise


class _WorkingClient:
    """A client whose bucket probe succeeds."""

    def head_bucket(self, **_kwargs: object) -> None:
        return None


class TestMinioErrorMapping:
    """Which failures are permanent and which are worth retrying.

    Getting this backwards is not a cosmetic bug: `ObjectNotFoundError` makes
    `run_resume_job` give up immediately, so a MinIO restart mapped onto it would
    permanently fail every resume uploaded during the restart.
    """

    @pytest.mark.parametrize(
        "error",
        [
            _client_error("NoSuchKey", 404),
            _client_error("NotFound", 404),
            _client_error("", 404),
        ],
    )
    async def test_a_missing_object_is_permanent(self, error):
        storage = MinioStorage(_FailingClient(error), "bucket")
        with pytest.raises(ObjectNotFoundError):
            await storage.get("resumes/c1/deadbeef.pdf")

    @pytest.mark.parametrize(
        "error",
        [
            _client_error("InternalError", 500),
            _client_error("SlowDown", 503),
            _client_error("RequestTimeout", 400),
            EndpointConnectionError(endpoint_url="http://localhost:9000"),
            TimeoutError("read timed out"),
        ],
    )
    async def test_everything_else_is_transient(self, error):
        """A `StorageError` that is not `ObjectNotFoundError` gets the retry budget."""
        storage = MinioStorage(_FailingClient(error), "bucket")
        with pytest.raises(StorageError) as caught:
            await storage.get("resumes/c1/deadbeef.pdf")
        assert not isinstance(caught.value, ObjectNotFoundError)

    async def test_exists_says_false_rather_than_raising_for_a_missing_key(self):
        storage = MinioStorage(_FailingClient(_client_error("NotFound", 404)), "bucket")
        assert await storage.exists("resumes/c1/deadbeef.pdf") is False

    async def test_exists_still_raises_when_minio_is_down(self):
        """The difference that matters: "no" is an answer, "I could not ask" is not.
        Swallowing an outage here would make the upload path think the blob is
        missing and rewrite it."""
        down = EndpointConnectionError(endpoint_url="http://localhost:9000")
        storage = MinioStorage(_FailingClient(down), "bucket")
        with pytest.raises(StorageError):
            await storage.exists("resumes/c1/deadbeef.pdf")

    def test_the_message_does_not_carry_the_key(self):
        """The storage key embeds the candidate id and the file's content hash, and
        a `StorageError` reaches logs. Resumes are PII."""
        storage = MinioStorage(_FailingClient(_client_error("InternalError", 500)), "bucket")
        error = storage._translate(_client_error("InternalError", 500), "resumes/c1/secret", "read")
        assert "resumes/c1/secret" not in str(error)


class TestBuildStorage:
    def test_local_is_the_default(self, tmp_path: Path):
        storage = build_storage(Settings(storage_dir=tmp_path, jwt_secret="x" * 40))
        assert isinstance(storage, LocalStorage)

    def test_an_unusable_bucket_fails_at_startup(self, monkeypatch):
        """A configuration fault should stop the process that is misconfigured,
        rather than being discovered on somebody's upload.

        The client is stubbed rather than pointed at a dead port: botocore retries
        with backoff, which would put nine seconds into every `pytest -q`. The real
        network case is covered in the opt-in `tests/test_minio.py`.
        """
        down = EndpointConnectionError(endpoint_url="http://localhost:9000")
        monkeypatch.setattr("app.storage.build_minio_client", lambda _s: _FailingClient(down))
        settings = Settings(
            storage_backend=StorageBackend.MINIO,
            minio_bucket="hirelens-typo",
            jwt_secret="x" * 40,
        )
        with pytest.raises(StorageError) as caught:
            build_storage(settings)
        assert "STORAGE_BACKEND=minio" in str(caught.value)
        assert "hirelens-typo" in str(caught.value)

    def test_a_reachable_bucket_builds_minio_storage(self, monkeypatch):
        monkeypatch.setattr("app.storage.build_minio_client", lambda _s: _WorkingClient())
        settings = Settings(storage_backend=StorageBackend.MINIO, jwt_secret="x" * 40)
        assert isinstance(build_storage(settings), MinioStorage)
