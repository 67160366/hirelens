"""Blob storage behind a narrow interface.

M1 writes to the local filesystem. M2 swaps in MinIO/S3 by adding one class here —
callers only ever see opaque `storage_key` strings, so nothing above this module
changes.
"""

from __future__ import annotations

import hashlib
import shutil
from abc import ABC, abstractmethod
from pathlib import Path

from app.config import Settings, StorageBackend


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


def build_storage(settings: Settings) -> Storage:
    match settings.storage_backend:
        case StorageBackend.LOCAL:
            return LocalStorage(settings.storage_path)
        case StorageBackend.MINIO:
            raise StorageError(
                "The MinIO backend arrives in M2. Use STORAGE_BACKEND=local for now."
            )
