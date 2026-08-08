"""The contract every `Storage` implementation has to satisfy.

Written once and run twice: against `LocalStorage` on every `pytest -q`
(`tests/test_storage.py`), and against a real MinIO when one is configured
(`tests/test_minio.py`). Two backends that pass different tests are two backends
that behave differently, and the whole point of the interface is that nothing above
`app/storage.py` can tell them apart.

Not a test module itself — the filename keeps pytest from collecting it directly,
so the cases run only where a `storage` fixture exists to run them against.
"""

from __future__ import annotations

import pytest

from app.storage import ObjectNotFoundError, build_storage_key


class StorageContract:
    """Subclass this and provide a `storage` fixture."""

    async def test_put_then_get_returns_the_same_bytes(self, storage):
        await storage.put("contract/roundtrip.bin", b"\x00\x01\x02hello")
        assert await storage.get("contract/roundtrip.bin") == b"\x00\x01\x02hello"

    async def test_a_missing_key_raises_object_not_found(self, storage):
        """The one error the retry policy reads as *permanent*: the object is gone,
        so trying again cannot help. Everything else must stay a plain
        `StorageError`, which is retried."""
        with pytest.raises(ObjectNotFoundError):
            await storage.get("contract/definitely-not-there.pdf")

    async def test_exists_answers_both_ways(self, storage):
        assert await storage.exists("contract/nothing-here.pdf") is False
        await storage.put("contract/here.pdf", b"%PDF-1.4")
        assert await storage.exists("contract/here.pdf") is True

    async def test_put_overwrites(self, storage):
        """Re-uploading the same file lands on the same key by design — the key is
        derived from the content hash — so writing twice has to be safe."""
        await storage.put("contract/overwrite.bin", b"first")
        await storage.put("contract/overwrite.bin", b"second")
        assert await storage.get("contract/overwrite.bin") == b"second"

    async def test_delete_is_idempotent(self, storage):
        await storage.put("contract/gone.bin", b"data")
        await storage.delete("contract/gone.bin")
        assert await storage.exists("contract/gone.bin") is False
        # Deleting it again must not raise: the upload path cleans up blobs on a
        # failed insert, and that cleanup can run after the object is already gone.
        await storage.delete("contract/gone.bin")

    async def test_a_realistic_key_round_trips(self, storage):
        """The keys this application actually generates: nested, uuid, hex digest."""
        key = build_storage_key(
            candidate_id="7f3d5c9a-1b2e-4d6f-8a0c-2e4f6a8b0c1d",
            digest="a" * 64,
            filename="ประวัติ.pdf",
        )
        await storage.put(key, b"%PDF-1.4 thai filename")
        assert await storage.get(key) == b"%PDF-1.4 thai filename"

    async def test_a_megabyte_survives(self, storage):
        """Resumes are small, but nothing above this module enforces that."""
        blob = bytes(range(256)) * 4096
        await storage.put("contract/big.bin", blob)
        assert await storage.get("contract/big.bin") == blob
