"""API tests: auth, upload, and reading a verified profile back."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.api.routes.resumes import MAX_UPLOAD_BYTES
from app.llm.fake import FakeMode
from app.models import ResumeStatus
from tests.conftest import resume_upload


class TestHealth:
    async def test_reports_the_active_provider(self, client: AsyncClient):
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "provider": "fake"}


class TestAuth:
    async def test_register_returns_a_token_pair(self, client: AsyncClient):
        response = await client.post(
            "/auth/register", json={"email": "new@example.com", "password": "a-good-password"}
        )
        assert response.status_code == 201
        body = response.json()
        assert body["access_token"] and body["refresh_token"]
        assert body["token_type"] == "bearer"

    async def test_duplicate_email_is_a_conflict(self, client: AsyncClient):
        payload = {"email": "dup@example.com", "password": "a-good-password"}
        assert (await client.post("/auth/register", json=payload)).status_code == 201
        second = await client.post("/auth/register", json=payload)
        assert second.status_code == 409

    async def test_email_is_normalized_to_lowercase(self, client: AsyncClient):
        await client.post(
            "/auth/register", json={"email": "MiXeD@Example.COM", "password": "a-good-password"}
        )
        response = await client.post(
            "/auth/login", json={"email": "mixed@example.com", "password": "a-good-password"}
        )
        assert response.status_code == 200

    async def test_short_password_is_rejected_before_hashing(self, client: AsyncClient):
        response = await client.post(
            "/auth/register", json={"email": "short@example.com", "password": "abc"}
        )
        assert response.status_code == 422

    @pytest.mark.parametrize(
        ("email", "password"),
        [
            ("nobody@example.com", "a-good-password"),
            ("known@example.com", "the-wrong-password"),
        ],
    )
    async def test_login_failures_are_indistinguishable(
        self, client: AsyncClient, email: str, password: str
    ):
        """The endpoint must not reveal whether an account exists."""
        await client.post(
            "/auth/register", json={"email": "known@example.com", "password": "a-good-password"}
        )
        response = await client.post("/auth/login", json={"email": email, "password": password})
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid email or password"

    async def test_me_requires_a_token(self, client: AsyncClient):
        assert (await client.get("/auth/me")).status_code == 401

    async def test_me_rejects_a_forged_token(self, client: AsyncClient):
        client.headers["Authorization"] = "Bearer not.a.real.token"
        assert (await client.get("/auth/me")).status_code == 401

    async def test_a_refresh_token_is_not_accepted_as_an_access_token(self, client: AsyncClient):
        registered = await client.post(
            "/auth/register", json={"email": "swap@example.com", "password": "a-good-password"}
        )
        refresh = registered.json()["refresh_token"]
        client.headers["Authorization"] = f"Bearer {refresh}"
        assert (await client.get("/auth/me")).status_code == 401

    async def test_me_returns_the_candidate(self, authed_client: AsyncClient):
        response = await authed_client.get("/auth/me")
        assert response.status_code == 200
        assert response.json()["email"] == "candidate@example.com"

    async def test_refresh_rotates_the_token_pair(self, client: AsyncClient):
        registered = await client.post(
            "/auth/register", json={"email": "fresh@example.com", "password": "a-good-password"}
        )
        pair = registered.json()

        response = await client.post("/auth/refresh", json={"refresh_token": pair["refresh_token"]})
        assert response.status_code == 200
        rotated = response.json()
        assert rotated["refresh_token"] != pair["refresh_token"]

        client.headers["Authorization"] = f"Bearer {rotated['access_token']}"
        assert (await client.get("/auth/me")).status_code == 200

    async def test_an_access_token_is_not_accepted_for_refresh(self, client: AsyncClient):
        registered = await client.post(
            "/auth/register", json={"email": "mixed-up@example.com", "password": "a-good-password"}
        )
        response = await client.post(
            "/auth/refresh", json={"refresh_token": registered.json()["access_token"]}
        )
        assert response.status_code == 401

    async def test_refresh_rejects_a_forged_token(self, client: AsyncClient):
        response = await client.post("/auth/refresh", json={"refresh_token": "not.a.token"})
        assert response.status_code == 401


class TestUpload:
    async def test_upload_requires_auth(self, client: AsyncClient):
        response = await client.post("/resumes", files=resume_upload())
        assert response.status_code == 401

    async def test_upload_extracts_a_profile(self, authed_client: AsyncClient):
        response = await authed_client.post("/resumes", files=resume_upload())
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == ResumeStatus.EXTRACTED
        assert body["page_count"] == 1
        assert body["failure_reason"] is None

    async def test_reuploading_the_same_bytes_is_idempotent(self, authed_client: AsyncClient):
        """Same file, same resource — no duplicate row and no second extraction."""
        first = await authed_client.post("/resumes", files=resume_upload())
        second = await authed_client.post("/resumes", files=resume_upload())

        assert first.status_code == 201
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]

        listing = await authed_client.get("/resumes")
        assert len(listing.json()) == 1

    async def test_rejects_a_non_pdf_extension(self, authed_client: AsyncClient):
        response = await authed_client.post(
            "/resumes", files={"file": ("resume.docx", b"not a pdf", "application/octet-stream")}
        )
        assert response.status_code == 415

    async def test_rejects_an_empty_upload(self, authed_client: AsyncClient):
        response = await authed_client.post(
            "/resumes", files={"file": ("resume.pdf", b"", "application/pdf")}
        )
        assert response.status_code == 400

    async def test_a_scanned_pdf_fails_with_an_explanation_not_a_500(
        self, authed_client: AsyncClient
    ):
        """The journey's "tell the user why" requirement, at the API boundary."""
        response = await authed_client.post("/resumes", files=resume_upload("resume_scanned.pdf"))
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == ResumeStatus.FAILED
        assert "OCR" in body["failure_reason"]

    async def test_a_disguised_non_pdf_is_rejected_by_magic_bytes(self, authed_client: AsyncClient):
        """The extension is caller-chosen; the first bytes are not."""
        response = await authed_client.post("/resumes", files=resume_upload("not_a_pdf.pdf"))
        assert response.status_code == 415

    async def test_an_oversized_upload_is_rejected(self, authed_client: AsyncClient):
        big = b"%PDF-1.7\n" + b"0" * MAX_UPLOAD_BYTES
        response = await authed_client.post(
            "/resumes", files={"file": ("resume.pdf", big, "application/pdf")}
        )
        assert response.status_code == 413

    async def test_corrupt_pdf_fails_with_an_explanation(self, authed_client: AsyncClient):
        """Right magic bytes, garbage body: passes the gate, fails the parser."""
        corrupt = b"%PDF-1.7\n" + b"this is not a real pdf body " * 4
        response = await authed_client.post(
            "/resumes", files={"file": ("resume.pdf", corrupt, "application/pdf")}
        )
        assert response.json()["status"] == ResumeStatus.FAILED

    async def test_partial_scan_reports_the_pages_needing_ocr(self, authed_client: AsyncClient):
        response = await authed_client.post(
            "/resumes", files=resume_upload("resume_mixed_scan.pdf")
        )
        body = response.json()
        assert body["status"] == ResumeStatus.EXTRACTED
        assert body["pages_without_text"] == [2]


class TestReadProfile:
    async def test_returns_verified_claims_with_evidence(self, authed_client: AsyncClient):
        uploaded = await authed_client.post("/resumes", files=resume_upload())
        resume_id = uploaded.json()["id"]

        response = await authed_client.get(f"/resumes/{resume_id}")
        assert response.status_code == 200
        body = response.json()

        profile = body["profile"]
        assert profile["full_name"]["value"] == "Somchai Jaidee"
        assert profile["stats"]["hallucination_rate"] == 0.0
        assert profile["stats"]["dropped"] == 0

    async def test_evidence_offsets_index_into_the_returned_document_text(
        self, authed_client: AsyncClient
    ):
        """The contract the highlighting UI depends on: offsets are resolvable
        against the text the API hands back, with no re-parsing."""
        uploaded = await authed_client.post("/resumes", files=resume_upload())
        response = await authed_client.get(f"/resumes/{uploaded.json()['id']}")
        body = response.json()

        text = body["document_text"]
        assert text

        evidence = body["profile"]["full_name"]["evidence"]
        assert text[evidence["char_start"] : evidence["char_end"]] == evidence["quote"]

        for skill in body["profile"]["skills"]:
            reference = skill["evidence"]
            assert text[reference["char_start"] : reference["char_end"]] == reference["quote"]

    async def test_another_candidates_resume_is_not_found(self, client: AsyncClient):
        """404 rather than 403 — the response should not confirm the id exists."""
        owner = await client.post(
            "/auth/register", json={"email": "owner@example.com", "password": "a-good-password"}
        )
        client.headers["Authorization"] = f"Bearer {owner.json()['access_token']}"
        uploaded = await client.post("/resumes", files=resume_upload())
        resume_id = uploaded.json()["id"]

        intruder = await client.post(
            "/auth/register", json={"email": "other@example.com", "password": "a-good-password"}
        )
        client.headers["Authorization"] = f"Bearer {intruder.json()['access_token']}"

        response = await client.get(f"/resumes/{resume_id}")
        assert response.status_code == 404

    async def test_unknown_resume_id_is_404(self, authed_client: AsyncClient):
        response = await authed_client.get("/resumes/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404

    async def test_malformed_resume_id_is_422(self, authed_client: AsyncClient):
        assert (await authed_client.get("/resumes/not-a-uuid")).status_code == 422


class TestHallucinationSurfacedThroughTheApi:
    @pytest.fixture
    def fake_mode(self) -> FakeMode:
        return FakeMode.HALLUCINATING

    async def test_unverifiable_claims_are_reported_not_hidden(self, authed_client: AsyncClient):
        uploaded = await authed_client.post("/resumes", files=resume_upload())
        response = await authed_client.get(f"/resumes/{uploaded.json()['id']}")
        profile = response.json()["profile"]

        assert profile["dropped"], "expected the fabricated claim to be reported"
        assert profile["stats"]["hallucination_rate"] > 0
        assert "Team leadership" not in [skill["value"] for skill in profile["skills"]]


class TestBackendOutage:
    @pytest.fixture
    def fake_mode(self) -> FakeMode:
        return FakeMode.UNAVAILABLE

    async def test_upload_survives_the_model_being_down(self, authed_client: AsyncClient):
        """The parse result is kept so a retry does not start from scratch."""
        response = await authed_client.post("/resumes", files=resume_upload())
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == ResumeStatus.PARSED
        assert "Extraction failed" in body["failure_reason"]
        assert body["page_count"] == 1
