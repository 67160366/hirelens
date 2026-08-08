"""API tests: auth, upload, and reading a verified profile back."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.api.routes.resumes import MAX_UPLOAD_BYTES
from app.llm.fake import FakeMode
from app.models import ResumeStatus
from tests.conftest import FIXTURES, resume_upload, upload_and_read


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


class TestChangePassword:
    """`authed_client` is registered as candidate@example.com / correct horse battery."""

    async def test_the_new_password_works_and_the_old_one_stops(self, authed_client: AsyncClient):
        response = await authed_client.post(
            "/auth/change-password",
            json={"current_password": "correct horse battery", "new_password": "a-brand-new-one"},
        )
        assert response.status_code == 200
        assert response.json()["access_token"]

        credentials = {"email": "candidate@example.com", "password": "correct horse battery"}
        assert (await authed_client.post("/auth/login", json=credentials)).status_code == 401

        credentials["password"] = "a-brand-new-one"
        assert (await authed_client.post("/auth/login", json=credentials)).status_code == 200

    async def test_a_wrong_current_password_is_refused(self, authed_client: AsyncClient):
        response = await authed_client.post(
            "/auth/change-password",
            json={"current_password": "not-it", "new_password": "a-brand-new-one"},
        )
        # 403, not 401: the token is valid, the claim about the old password is not.
        assert response.status_code == 403

        credentials = {"email": "candidate@example.com", "password": "correct horse battery"}
        assert (await authed_client.post("/auth/login", json=credentials)).status_code == 200

    async def test_it_requires_authentication(self, client: AsyncClient):
        response = await client.post(
            "/auth/change-password",
            json={"current_password": "anything", "new_password": "a-brand-new-one"},
        )
        assert response.status_code == 401

    async def test_a_short_new_password_is_rejected(self, authed_client: AsyncClient):
        response = await authed_client.post(
            "/auth/change-password",
            json={"current_password": "correct horse battery", "new_password": "abc"},
        )
        assert response.status_code == 422

    async def test_tokens_issued_before_the_change_still_work(self, authed_client: AsyncClient):
        """KNOWN LIMITATION, pinned so it is a deliberate state rather than a surprise.

        Revoking the old pair needs a refresh-token denylist, which is also what a
        real `/auth/logout` would need. When that lands, this test should fail and
        be replaced with its opposite.
        """
        old_token = authed_client.headers["Authorization"]
        await authed_client.post(
            "/auth/change-password",
            json={"current_password": "correct horse battery", "new_password": "a-brand-new-one"},
        )

        authed_client.headers["Authorization"] = old_token
        assert (await authed_client.get("/auth/me")).status_code == 200


class TestUpload:
    async def test_upload_requires_auth(self, client: AsyncClient):
        response = await client.post("/resumes", files=resume_upload())
        assert response.status_code == 401

    async def test_upload_accepts_the_file_and_answers_pending(self, authed_client: AsyncClient):
        """Parsing happens off the request, so the response cannot carry a profile.

        The status is `pending` whichever queue backend is configured — the
        response describes the resume as accepted, not as processed, so a client
        polls the same way against an inline queue and a real worker.
        """
        response = await authed_client.post("/resumes", files=resume_upload())
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == ResumeStatus.PENDING
        assert body["page_count"] is None
        assert body["failure_reason"] is None

    async def test_the_queued_work_produces_a_profile(self, authed_client: AsyncClient):
        body = await upload_and_read(authed_client)
        assert body["resume"]["status"] == ResumeStatus.EXTRACTED
        assert body["resume"]["page_count"] == 1
        assert body["resume"]["failure_reason"] is None
        assert body["profile"] is not None

    async def test_reuploading_the_same_bytes_is_idempotent(self, authed_client: AsyncClient):
        """Same file, same resource — no duplicate row and no second extraction."""
        first = await authed_client.post("/resumes", files=resume_upload())
        second = await authed_client.post("/resumes", files=resume_upload())

        assert first.status_code == 201
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]

        listing = await authed_client.get("/resumes")
        assert len(listing.json()) == 1

    async def test_rejects_an_unsupported_extension(self, authed_client: AsyncClient):
        response = await authed_client.post(
            "/resumes", files={"file": ("resume.rtf", b"{\\rtf1}", "application/rtf")}
        )
        assert response.status_code == 415

    async def test_accepts_a_docx(self, authed_client: AsyncClient):
        body = await upload_and_read(authed_client, "resume_th.docx")
        assert body["resume"]["status"] == ResumeStatus.EXTRACTED
        # A .docx has no pages, so it is reported as the single page it is.
        assert body["resume"]["page_count"] == 1
        assert body["profile"] is not None

    async def test_a_pdf_renamed_to_docx_is_rejected_by_magic_bytes(
        self, authed_client: AsyncClient
    ):
        """Each accepted type has its own signature, so the gate cannot be fooled
        by relabelling one as the other."""
        data = (FIXTURES / "resume_en.pdf").read_bytes()
        response = await authed_client.post(
            "/resumes",
            files={"file": ("resume.docx", data, "application/octet-stream")},
        )
        assert response.status_code == 415
        assert "DOCX" in response.json()["detail"]

    async def test_rejects_an_empty_upload(self, authed_client: AsyncClient):
        response = await authed_client.post(
            "/resumes", files={"file": ("resume.pdf", b"", "application/pdf")}
        )
        assert response.status_code == 400

    async def test_a_scanned_pdf_fails_with_an_explanation_not_a_500(
        self, authed_client: AsyncClient
    ):
        """The journey's "tell the user why" requirement, at the API boundary."""
        body = await upload_and_read(authed_client, "resume_scanned.pdf")
        assert body["resume"]["status"] == ResumeStatus.FAILED
        assert "OCR" in body["resume"]["failure_reason"]

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
        uploaded = await authed_client.post(
            "/resumes", files={"file": ("resume.pdf", corrupt, "application/pdf")}
        )
        response = await authed_client.get(f"/resumes/{uploaded.json()['id']}")
        assert response.json()["resume"]["status"] == ResumeStatus.FAILED

    async def test_partial_scan_reports_the_pages_needing_ocr(self, authed_client: AsyncClient):
        body = await upload_and_read(authed_client, "resume_mixed_scan.pdf")
        assert body["resume"]["status"] == ResumeStatus.EXTRACTED
        assert body["resume"]["pages_without_text"] == [2]


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
        """A backend outage is transient, so the resume waits rather than failing.

        It goes back to `pending` with the reason recorded, and the parse result is
        kept — `page_count` proves it — so the retry starts from extraction rather
        than from the PDF.
        """
        body = await upload_and_read(authed_client)
        assert body["resume"]["status"] == ResumeStatus.PENDING
        assert "retrying" in body["resume"]["failure_reason"]
        assert "LLMUnavailableError" in body["resume"]["failure_reason"]
        assert body["resume"]["page_count"] == 1
        assert body["resume"]["attempts"] == 1
        assert body["document_text"] is not None
