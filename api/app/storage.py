"""Blob storage behind a narrow interface.

M1 wrote to the local filesystem; M2 added MinIO. Callers only ever see opaque
`storage_key` strings, so nothing above this module knows which one is running.

Two things in the MinIO half are worth reading before changing it:

*   **Only a missing object may raise `ObjectNotFoundError`.** `jobs.is_retryable`
    treats that exception as a *permanent* failure — the file is gone, so trying
    again cannot help. Every other fault (MinIO restarting, a timeout, a refused
    connection) has to come back as plain `StorageError`, which the same policy
    treats as transient and retries. Mapping an outage onto "not found" would turn
    a thirty-second restart into a permanent `failed` on somebody's resume.
*   **A missing bucket is refused at startup**, not discovered on the first upload,
    for the same reason `build_ocr_engine` probes its language packs there: a
    configuration fault should stop the process that is misconfigured.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.config import Settings, StorageBackend

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client


class StorageError(Exception):
    pass


class ObjectNotFoundError(StorageError):
    pass


def content_hash(data: bytes) -> str:
    """SHA-256 of the uploaded bytes — the dedupe and idempotency key."""
    return hashlib.sha256(data).hexdigest()


def build_storage_key(*, candidate_id: str, digest: str, filename: str) -> str:
    """A key derived from content, not from the upload's name.

    Two candidates uploading the same file get separate objects; the same candidate
    re-uploading gets the same key, which is what makes re-upload idempotent.
    """
    suffix = Path(filename).suffix.lower()[:10]
    return f"resumes/{candidate_id}/{digest}{suffix}"


class Storage(ABC):
    @abstractmethod
    async def put(self, key: str, data: bytes) -> None: ...

    @abstractmethod
    async def get(self, key: str) -> bytes: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...


class LocalStorage(Storage):
    """Filesystem-backed storage rooted at one directory."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path_for(self, key: str) -> Path:
        # Keys are built by this module, never taken from a request, but resolve and
        # check anyway: one careless caller should not be able to escape the root.
        candidate = (self._root / key).resolve()
        root = self._root.resolve()
        if not candidate.is_relative_to(root):
            raise StorageError(f"Refusing to operate outside the storage root: {key!r}")
        return candidate

    async def put(self, key: str, data: bytes) -> None:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a sibling then rename, so a crash mid-write cannot leave a
        # truncated object under a key the database already points at.
        temporary = path.with_suffix(path.suffix + ".partial")
        temporary.write_bytes(data)
        temporary.replace(path)

    async def get(self, key: str) -> bytes:
        path = self._path_for(key)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise ObjectNotFoundError(key) from exc

    async def delete(self, key: str) -> None:
        self._path_for(key).unlink(missing_ok=True)

    async def exists(self, key: str) -> bool:
        return self._path_for(key).is_file()

    def clear(self) -> None:
        """Remove everything under the root. Tests only."""
        if self._root.exists():
            shutil.rmtree(self._root)


class MinioStorage(Storage):
    """Object storage over the S3 API — MinIO in development, S3 anywhere else.

    `boto3` is synchronous, so every call runs in a worker thread. That is the same
    move `process_resume` makes for parsing: the API serves progress streams on the
    event loop and must not block on somebody else's network.
    """

    def __init__(self, client: S3Client, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    async def put(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(self._put, key, data)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._get, key)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._delete, key)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._exists, key)

    def _put(self, key: str, data: bytes) -> None:
        try:
            self._client.put_object(Bucket=self._bucket, Key=key, Body=data)
        except Exception as exc:
            raise self._translate(exc, key, "store") from exc

    def _get(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            body: bytes = response["Body"].read()
            return body
        except Exception as exc:
            raise self._translate(exc, key, "read") from exc

    def _delete(self, key: str) -> None:
        # S3 deletes are idempotent: removing a key that is not there succeeds,
        # which matches `LocalStorage`'s `missing_ok=True`.
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            raise self._translate(exc, key, "delete") from exc

    def _exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception as exc:
            translated = self._translate(exc, key, "stat")
            if isinstance(translated, ObjectNotFoundError):
                return False
            raise translated from exc

    def _translate(self, exc: Exception, key: str, action: str) -> StorageError:
        """Turn a botocore failure into the right side of the retry policy.

        Read the class docstring before widening the `ObjectNotFoundError` branch:
        it is the *permanent* verdict, and only a genuinely absent object earns it.
        The message deliberately carries the bucket and the error code but not the
        key, which embeds the candidate id and the file's content hash.
        """
        if _is_missing_object(exc):
            return ObjectNotFoundError(key)
        return StorageError(f"Could not {action} object in bucket {self._bucket!r}: {exc!r}")


def _is_missing_object(exc: Exception) -> bool:
    """True only for "this key is not there", never for "MinIO did not answer"."""
    from botocore.exceptions import ClientError

    if not isinstance(exc, ClientError):
        return False
    response: dict[str, Any] = exc.response  # type: ignore[assignment]
    code = str(response.get("Error", {}).get("Code", ""))
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in {"NoSuchKey", "NoSuchBucket", "404", "NotFound"} or status == 404


def build_minio_client(settings: Settings) -> S3Client:
    import boto3
    from botocore.config import Config

    client: S3Client = boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        region_name=settings.minio_region,
        # Bounded, for the same reason the OCR subprocess has a timeout: a wedged
        # dependency should fail the job and let the retry policy decide, not hold
        # a worker open indefinitely.
        config=Config(
            connect_timeout=5,
            read_timeout=30,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )
    return client


def build_storage(settings: Settings) -> Storage:
    match settings.storage_backend:
        case StorageBackend.LOCAL:
            return LocalStorage(settings.storage_path)
        case StorageBackend.MINIO:
            client = build_minio_client(settings)
            _require_bucket(client, settings)
            return MinioStorage(client, settings.minio_bucket)


def _require_bucket(client: S3Client, settings: Settings) -> None:
    """Fail at startup if the bucket is missing or MinIO is unreachable.

    The alternative is discovering it on the first upload, which reports a broken
    deployment as a broken resume. Bucket creation is deliberately *not* done here:
    `docker-compose.yml` creates it in a one-shot service, the same shape migrations
    use, so nothing races and a typo in the name fails loudly instead of quietly
    creating a second bucket.
    """
    try:
        client.head_bucket(Bucket=settings.minio_bucket)
    except Exception as exc:
        raise StorageError(
            f"STORAGE_BACKEND=minio but bucket {settings.minio_bucket!r} is not usable at "
            f"{settings.minio_endpoint!r}: {exc!r}. Create it (docker compose runs a "
            "`createbucket` service that does), or set STORAGE_BACKEND=local."
        ) from exc
