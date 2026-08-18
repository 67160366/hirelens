"""API tests: auth, upload, and reading a verified profile back."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.api.routes.resumes import MAX_UPLOAD_BYTES
from app.llm.fake import FakeMode
from app.models import ResumeStatus
from tests.conftest import CONSENT, FIXTURES, resume_upload, upload_and_read


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

    async def test_the_token_that_changed_the_password_stops_working(
        self, authed_client: AsyncClient
    ):
        """This test is the opposite of the one it replaces, which is the point.

        It used to read `test_tokens_issued_before_the_change_still_work` and pin a
        **known limitation**: with no denylist, the credential that proved the old
        password went on working after the password had changed. Its docstring said
        that when revocation landed this test should fail and be replaced with its
        opposite — and on 2026-08-16 it did fail, for exactly that reason.

        Same shape as `test_columns_should_read_one_after_the_other` in
        `test_parse.py`: a test written to break the day the limitation is removed
        is worth more than a comment nobody re-reads.
        """
        old_token = authed_client.headers["Authorization"]
        changed = await authed_client.post(
            "/auth/change-password",
            json={"current_password": "correct horse battery", "new_password": "a-brand-new-one"},
        )
        assert changed.status_code == 200

        authed_client.headers["Authorization"] = old_token
        assert (await authed_client.get("/auth/me")).status_code == 401

        # And the pair it handed back is usable, or the route would have signed the
        # caller out of the session it was standing in.
        authed_client.headers["Authorization"] = f"Bearer {changed.json()['access_token']}"
        assert (await authed_client.get("/auth/me")).status_code == 200

    async def test_a_session_on_another_device_is_signed_out_by_a_password_change(
        self, authed_client: AsyncClient, client: AsyncClient
    ):
        """The opposite of the test that used to stand here, which is the point.

        It read `test_a_session_on_another_device_survives_a_password_change` and
        pinned a **known limitation**: the denylist records tokens that are dead and
        never tokens that are outstanding, so a password change had no list of other
        sessions to walk and one on another machine kept working for the refresh
        token's full fourteen days. Its docstring named the two fixes and said that
        when one landed this should fail and be replaced with its opposite. On
        2026-08-18 it did fail, for exactly that reason: `Candidate.token_epoch`.

        Third time this device has been used here, after
        `test_columns_should_read_one_after_the_other` and
        `test_the_token_that_changed_the_password_stops_working`.

        Both halves of the pair are checked, not just the access token: the refresh
        token is the one that could otherwise mint new access tokens for a fortnight,
        so a change that only killed the access token would have looked like a fix
        for thirty minutes and then quietly not been one.
        """
        credentials = {"email": "candidate@example.com", "password": "correct horse battery"}
        elsewhere = (await client.post("/auth/login", json=credentials)).json()

        await authed_client.post(
            "/auth/change-password",
            json={"current_password": "correct horse battery", "new_password": "a-brand-new-one"},
        )

        client.headers["Authorization"] = f"Bearer {elsewhere['access_token']}"
        assert (await client.get("/auth/me")).status_code == 401

        refreshed = await client.post(
            "/auth/refresh", json={"refresh_token": elsewhere["refresh_token"]}
        )
        assert refreshed.status_code == 401

    async def test_the_other_device_can_sign_in_again_with_the_new_password(
        self, authed_client: AsyncClient, client: AsyncClient
    ):
        """Signed out is not locked out.

        The epoch ends a generation of tokens, not the account — so the check above
        would also pass if a password change had bricked it. Worth its own case,
        because "everything is refused" is the failure mode a too-eager epoch
        comparison produces and it looks identical from the other test's angle.
        """
        await authed_client.post(
            "/auth/change-password",
            json={"current_password": "correct horse battery", "new_password": "a-brand-new-one"},
        )

        again = await client.post(
            "/auth/login",
            json={"email": "candidate@example.com", "password": "a-brand-new-one"},
        )
        assert again.status_code == 200

        client.headers["Authorization"] = f"Bearer {again.json()['access_token']}"
        assert (await client.get("/auth/me")).status_code == 200

    async def test_two_password_changes_do_not_reopen_the_first_generation(
        self, authed_client: AsyncClient, client: AsyncClient
    ):
        """A counter, not a toggle.

        The epoch is compared for equality against a row that only ever increases,
        so a second change cannot bring a token from before the first one back. This
        is the case that would fail if the epoch were ever stored as a boolean or
        reset on any path.
        """
        credentials = {"email": "candidate@example.com", "password": "correct horse battery"}
        oldest = (await client.post("/auth/login", json=credentials)).json()["access_token"]

        first = await authed_client.post(
            "/auth/change-password",
            json={"current_password": "correct horse battery", "new_password": "second-password"},
        )
        assert first.status_code == 200

        authed_client.headers["Authorization"] = f"Bearer {first.json()['access_token']}"
        second = await authed_client.post(
            "/auth/change-password",
            json={"current_password": "second-password", "new_password": "third-password"},
        )
        assert second.status_code == 200

        client.headers["Authorization"] = f"Bearer {oldest}"
        assert (await client.get("/auth/me")).status_code == 401

    async def test_a_token_minted_before_the_epoch_existed_still_works(
        self, authed_client: AsyncClient, client: AsyncClient
    ):
        """Tokens already in browsers when this landed carry no `epoch` claim.

        `decode_token` reads a missing one as zero and the migration starts every
        account at zero, so they match — nothing signed anybody out on deploy, the
        same way the denylist changed nothing about tokens already issued. They are
        not grandfathered past anything: the case below is the same token after a
        password change, and it is refused with everything else.
        """
        import jwt

        settings = client._transport.app.state.settings  # type: ignore[union-attr]
        subject = (await authed_client.get("/auth/me")).json()["id"]
        legacy = jwt.encode(
            {
                "sub": subject,
                "type": "access",
                "exp": datetime.now(UTC) + timedelta(minutes=5),
                "jti": uuid.uuid4().hex,
            },
            settings.jwt_secret,
            algorithm="HS256",
        )

        client.headers["Authorization"] = f"Bearer {legacy}"
        assert (await client.get("/auth/me")).status_code == 200

        await authed_client.post(
            "/auth/change-password",
            json={"current_password": "correct horse battery", "new_password": "a-brand-new-one"},
        )
        assert (await client.get("/auth/me")).status_code == 401


class TestUpload:
    async def test_upload_requires_auth(self, client: AsyncClient):
        response = await client.post("/resumes", **resume_upload())
        assert response.status_code == 401

    async def test_upload_accepts_the_file_and_answers_pending(self, authed_client: AsyncClient):
        """Parsing happens off the request, so the response cannot carry a profile.

        The status is `pending` whichever queue backend is configured — the
        response describes the resume as accepted, not as processed, so a client
        polls the same way against an inline queue and a real worker.
        """
        response = await authed_client.post("/resumes", **resume_upload())
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
        first = await authed_client.post("/resumes", **resume_upload())
        second = await authed_client.post("/resumes", **resume_upload())

        assert first.status_code == 201
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]

        listing = await authed_client.get("/resumes")
        assert len(listing.json()) == 1

    async def test_rejects_an_unsupported_extension(self, authed_client: AsyncClient):
        response = await authed_client.post(
            "/resumes", files={"file": ("resume.rtf", b"{\\rtf1}", "application/rtf")}, data=CONSENT
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
            data=CONSENT,
        )
        assert response.status_code == 415
        assert "DOCX" in response.json()["detail"]

    async def test_rejects_an_empty_upload(self, authed_client: AsyncClient):
        response = await authed_client.post(
            "/resumes", files={"file": ("resume.pdf", b"", "application/pdf")}, data=CONSENT
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
        response = await authed_client.post("/resumes", **resume_upload("not_a_pdf.pdf"))
        assert response.status_code == 415

    async def test_an_oversized_upload_is_rejected(self, authed_client: AsyncClient):
        big = b"%PDF-1.7\n" + b"0" * MAX_UPLOAD_BYTES
        response = await authed_client.post(
            "/resumes", files={"file": ("resume.pdf", big, "application/pdf")}, data=CONSENT
        )
        assert response.status_code == 413

    async def test_corrupt_pdf_fails_with_an_explanation(self, authed_client: AsyncClient):
        """Right magic bytes, garbage body: passes the gate, fails the parser."""
        corrupt = b"%PDF-1.7\n" + b"this is not a real pdf body " * 4
        uploaded = await authed_client.post(
            "/resumes", files={"file": ("resume.pdf", corrupt, "application/pdf")}, data=CONSENT
        )
        response = await authed_client.get(f"/resumes/{uploaded.json()['id']}")
        assert response.json()["resume"]["status"] == ResumeStatus.FAILED

    async def test_partial_scan_reports_the_pages_needing_ocr(self, authed_client: AsyncClient):
        body = await upload_and_read(authed_client, "resume_mixed_scan.pdf")
        assert body["resume"]["status"] == ResumeStatus.EXTRACTED
        assert body["resume"]["pages_without_text"] == [2]


class TestReadProfile:
    async def test_returns_verified_claims_with_evidence(self, authed_client: AsyncClient):
        uploaded = await authed_client.post("/resumes", **resume_upload())
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
        uploaded = await authed_client.post("/resumes", **resume_upload())
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
        uploaded = await client.post("/resumes", **resume_upload())
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
        uploaded = await authed_client.post("/resumes", **resume_upload())
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
