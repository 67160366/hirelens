"""Retrieval: which resumes are worth paying to judge.

Pure, like `test_judge.py` and `test_ranking.py` — no session for the scoring half.

The load-bearing cases are the Thai ones, and they are written to fail against the
obvious implementation. `resume_th.pdf` contains the 31-character unbroken run
`ดูแลระบบกระทบยอดการชำระเงินด้วย`; a whitespace tokenizer cannot see `ชำระเงิน` inside
it. The word `ทักษะ` *is* a standalone token in the same document, so a test written
with that term alone passes against a tokenizer that is wrong for Thai. Measured
before the module was written — `docs/HANDOFF.md` records the numbers.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import RetrievalBackend, Settings
from app.jobs import JobContext, run_resume_job
from app.llm.fake import FakeExtractor, FakeMode
from app.pipeline.retrieval import (
    LexicalRetriever,
    RetrievableDocument,
    RetrievalError,
    build_retriever,
    tokenize,
)
from app.storage import LocalStorage
from tests.conftest import resume_upload
from tests.test_worker import RecordingQueue

# The real line out of the Thai fixture, not a hand-made one: the terms below sit
# inside it with no space on either side.
THAI_LINE = "ดูแลระบบกระทบยอดการชำระเงินด้วย Python และ PostgreSQL"


@pytest.fixture
async def authed_client(recruiter_client: AsyncClient) -> AsyncClient:
    """This whole module is the recruiter side, so the default client is one."""
    return recruiter_client


@pytest.fixture
def queue() -> RecordingQueue:
    """Replaces the inline queue, so the resume job runs deliberately and a
    requested screening is recorded rather than executed."""
    return RecordingQueue()


@pytest.fixture
def context(
    settings: Settings,
    sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    fake_mode: FakeMode,
) -> JobContext:
    return JobContext(
        sessionmaker=sessionmaker_for_tests,
        storage=LocalStorage(settings.storage_path),
        extractor=FakeExtractor(fake_mode),
        settings=settings,
    )


def doc(resume_id: str, text: str) -> RetrievableDocument:
    return RetrievableDocument(resume_id=resume_id, text=text)


def scores(hits: list) -> dict[str, float]:
    return {hit.resume_id: hit.score for hit in hits}


class TestTokenize:
    def test_latin_words_survive_whole(self) -> None:
        assert "python" in tokenize("Python and PostgreSQL")
        assert "postgresql" in tokenize("Python and PostgreSQL")

    def test_matching_ignores_case(self) -> None:
        assert tokenize("PYTHON") == tokenize("python")

    def test_a_one_character_latin_token_carries_no_signal(self) -> None:
        assert tokenize("a b Go") == ["go"]

    def test_thai_becomes_overlapping_ngrams(self) -> None:
        tokens = tokenize("ชำระเงิน")
        assert "ชำร" in tokens
        assert all(len(token) == 3 for token in tokens)

    def test_a_thai_term_buried_mid_run_is_still_found(self) -> None:
        # The case a whitespace tokenizer fails: no space anywhere near it.
        buried = set(tokenize(THAI_LINE))
        assert set(tokenize("ชำระเงิน")) <= buried

    def test_a_thai_run_shorter_than_one_ngram_is_kept_whole(self) -> None:
        assert tokenize("ไทย") == ["ไทย"]

    def test_mixed_scripts_in_one_line_both_tokenize(self) -> None:
        tokens = set(tokenize(THAI_LINE))
        assert "python" in tokens
        assert set(tokenize("ชำระเงิน")) <= tokens


class TestLexicalRetriever:
    def test_a_document_containing_the_term_outranks_one_that_does_not(self) -> None:
        hits = LexicalRetriever().retrieve(
            ["Kubernetes"],
            [doc("a", "Python and PostgreSQL"), doc("b", "Kubernetes and Terraform")],
        )
        assert [hit.resume_id for hit in hits] == ["b", "a"]

    def test_a_thai_requirement_matches_a_document_with_no_word_spaces(self) -> None:
        # The whole reason this module tokenizes Thai by n-gram. Against a
        # whitespace tokenizer both documents score zero and the order is arbitrary.
        hits = LexicalRetriever().retrieve(
            ["ชำระเงิน"],
            [doc("no", "Kubernetes and Terraform"), doc("yes", THAI_LINE)],
        )
        assert [hit.resume_id for hit in hits] == ["yes", "no"]
        assert scores(hits)["yes"] > 0
        assert scores(hits)["no"] == 0

    def test_the_matched_term_is_reported_as_typed(self) -> None:
        # Not the n-gram that actually hit — a person typed the term and has to be
        # able to recognise it in the answer.
        hits = LexicalRetriever().retrieve(["ชำระเงิน"], [doc("a", THAI_LINE)])
        assert hits[0].matched == ["ชำระเงิน"]

    def test_a_term_no_document_contains_matches_nothing(self) -> None:
        hits = LexicalRetriever().retrieve(["Kubernetes"], [doc("a", "Python")])
        assert hits[0].matched == []
        assert hits[0].score == 0

    def test_a_term_every_document_shares_cannot_separate_them(self) -> None:
        # The IDF half. "Python" is in both, so it must not decide the order;
        # "Kubernetes" is in one, so it must.
        hits = LexicalRetriever().retrieve(
            ["Python", "Kubernetes"],
            [doc("a", "Python"), doc("b", "Python Kubernetes")],
        )
        assert [hit.resume_id for hit in hits] == ["b", "a"]

    def test_more_of_a_phrase_present_scores_higher(self) -> None:
        hits = LexicalRetriever().retrieve(
            ["Python FastAPI PostgreSQL"],
            [doc("some", "Python only"), doc("all", "Python FastAPI PostgreSQL")],
        )
        assert scores(hits)["all"] > scores(hits)["some"]


class TestItIsAHintNotAGate:
    """The property this module must not lose.

    A retriever that dropped its tail would remove a person from consideration with
    no way to see it happened — the same failure as a UI that hides `excluded`.
    """

    def test_every_document_comes_back_even_with_no_terms(self) -> None:
        documents = [doc("a", "Python"), doc("b", "Kubernetes"), doc("c", "")]
        hits = LexicalRetriever().retrieve([], documents)
        assert {hit.resume_id for hit in hits} == {"a", "b", "c"}

    def test_a_document_matching_nothing_is_returned_last_not_dropped(self) -> None:
        hits = LexicalRetriever().retrieve(
            ["Kubernetes"],
            [doc("nothing", "unrelated text"), doc("match", "Kubernetes")],
        )
        assert [hit.resume_id for hit in hits] == ["match", "nothing"]
        assert len(hits) == 2

    def test_an_empty_document_is_scored_rather_than_skipped(self) -> None:
        hits = LexicalRetriever().retrieve(["Python"], [doc("empty", "")])
        assert [hit.resume_id for hit in hits] == ["empty"]
        assert hits[0].score == 0

    def test_no_documents_is_an_empty_answer_not_an_error(self) -> None:
        assert LexicalRetriever().retrieve(["Python"], []) == []


class TestTheOrderIsTotal:
    def test_documents_that_tie_are_separated_by_id(self) -> None:
        # Two documents that genuinely tie, so there is something to be stable
        # about. `test_ranking.py` learned that a determinism test over distinct
        # scores cannot fail (docs/NOTES.md 2026-08-08).
        hits = LexicalRetriever().retrieve(["Python"], [doc("b", "Python"), doc("a", "Python")])
        assert [hit.resume_id for hit in hits] == ["a", "b"]

    def test_input_order_does_not_change_the_result(self) -> None:
        documents = [doc("b", "Python"), doc("a", "Python"), doc("c", "Python")]
        forward = LexicalRetriever().retrieve(["Python"], documents)
        backward = LexicalRetriever().retrieve(["Python"], list(reversed(documents)))
        assert [hit.resume_id for hit in forward] == [hit.resume_id for hit in backward]


class TestBuildRetriever:
    def test_lexical_is_the_default(self) -> None:
        assert isinstance(build_retriever(Settings()), LexicalRetriever)

    def test_pgvector_raises_rather_than_half_working(self) -> None:
        # Same rule as `LLM_PROVIDER=anthropic`: an adapter nobody has run against
        # the real thing is worse than an honest error, and embeddings are a paid
        # call that needs a price table first.
        settings = Settings(retrieval_backend=RetrievalBackend.PGVECTOR)
        with pytest.raises(RetrievalError, match="not implemented"):
            build_retriever(settings)


@pytest.mark.anyio
class TestTheCandidatesRoute:
    """`GET /jobs/{id}/candidates` — where to spend the next model call."""

    async def _job(self, client: AsyncClient, **overrides: object) -> str:
        payload: dict[str, object] = {
            "title": "Backend Engineer",
            "requirements": [{"kind": "skill", "label": "Kubernetes"}],
        }
        payload.update(overrides)
        response = await client.post("/jobs", json=payload)
        assert response.status_code == 201, response.text
        return str(response.json()["id"])

    async def test_it_orders_the_callers_resumes(
        self, authed_client: AsyncClient, context: JobContext
    ) -> None:
        job_id = await self._job(authed_client)

        for name in ("resume_en.pdf", "resume_two_column.pdf"):
            uploaded = await authed_client.post("/resumes", **resume_upload(name))
            assert uploaded.status_code in (200, 201), uploaded.text
            await run_resume_job(context, uuid.UUID(uploaded.json()["id"]))

        response = await authed_client.get(f"/jobs/{job_id}/candidates")
        assert response.status_code == 200, response.text
        body = response.json()

        # The two-column fixture is the one that mentions Kubernetes.
        assert body[0]["filename"] == "resume_two_column.pdf"
        assert body[0]["matched"] == ["Kubernetes"]
        assert body[0]["score"] > 0

    async def test_a_resume_matching_nothing_is_listed_last_not_hidden(
        self, authed_client: AsyncClient, context: JobContext
    ) -> None:
        # The hint-not-a-gate property, over HTTP. A person who drops off this list
        # silently is a person nobody screens and nobody can see was skipped.
        job_id = await self._job(authed_client)

        for name in ("resume_en.pdf", "resume_two_column.pdf"):
            uploaded = await authed_client.post("/resumes", **resume_upload(name))
            await run_resume_job(context, uuid.UUID(uploaded.json()["id"]))

        body = (await authed_client.get(f"/jobs/{job_id}/candidates")).json()
        assert len(body) == 2
        assert body[-1]["matched"] == []

    async def test_it_spends_nothing(self, authed_client: AsyncClient, context: JobContext) -> None:
        job_id = await self._job(authed_client)
        uploaded = await authed_client.post("/resumes", **resume_upload())
        await run_resume_job(context, uuid.UUID(uploaded.json()["id"]))

        before = (await authed_client.get(f"/jobs/{job_id}/screenings")).json()
        await authed_client.get(f"/jobs/{job_id}/candidates")
        after = (await authed_client.get(f"/jobs/{job_id}/screenings")).json()

        # No screening was created, so no model call was billed.
        assert before == after == []

    async def test_an_unparsed_resume_is_not_offered(self, authed_client: AsyncClient) -> None:
        # Uploaded but never run, so it has no `document_text`. Screening it would
        # raise `NotScreenable`, and offering it would promise work that must fail.
        job_id = await self._job(authed_client)
        uploaded = await authed_client.post("/resumes", **resume_upload())
        assert uploaded.status_code in (200, 201)

        body = (await authed_client.get(f"/jobs/{job_id}/candidates")).json()
        assert body == []

    async def test_a_screened_resume_says_so_and_still_appears(
        self, authed_client: AsyncClient, context: JobContext, queue: RecordingQueue
    ) -> None:
        job_id = await self._job(authed_client)
        uploaded = await authed_client.post("/resumes", **resume_upload())
        resume_id = uploaded.json()["id"]
        await run_resume_job(context, uuid.UUID(resume_id))

        created = await authed_client.post(
            f"/jobs/{job_id}/screenings", json={"resume_id": resume_id}
        )
        assert created.status_code == 202, created.text

        body = (await authed_client.get(f"/jobs/{job_id}/candidates")).json()
        assert [entry["resume_id"] for entry in body] == [resume_id]
        assert body[0]["already_screened"] is True

    async def test_the_description_does_not_steer_retrieval(
        self, authed_client: AsyncClient, context: JobContext
    ) -> None:
        # The description is stored for context and audit and is deliberately not
        # what anyone is judged against. Letting it match would reintroduce free-text
        # scoring on the one input nobody decomposed on purpose.
        job_id = await self._job(
            authed_client,
            requirements=[{"kind": "skill", "label": "Rust"}],
            description="Kubernetes Terraform gRPC",
        )
        uploaded = await authed_client.post("/resumes", **resume_upload("resume_two_column.pdf"))
        await run_resume_job(context, uuid.UUID(uploaded.json()["id"]))

        body = (await authed_client.get(f"/jobs/{job_id}/candidates")).json()
        assert body[0]["matched"] == []
        assert body[0]["score"] == 0

    async def test_another_candidates_job_is_not_found(self, client: AsyncClient) -> None:
        first = await client.post(
            "/auth/register",
            json={"email": "one@example.com", "password": "correct horse b", "role": "recruiter"},
        )
        client.headers["Authorization"] = f"Bearer {first.json()['access_token']}"
        job_id = await self._job(client)

        second = await client.post(
            "/auth/register",
            json={"email": "two@example.com", "password": "correct horse b", "role": "recruiter"},
        )
        client.headers["Authorization"] = f"Bearer {second.json()['access_token']}"

        response = await client.get(f"/jobs/{job_id}/candidates")
        assert response.status_code == 404
