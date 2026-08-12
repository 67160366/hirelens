"""Ordering candidates for one job.

The first module in this project where the output is a *comparison between people*,
so the things worth pinning are the ones that would quietly produce a plausible
wrong order:

*   **`must_have` is a gate, not a heavy weight.** A candidate missing one ranks
    below every candidate that has them all, however well they score elsewhere.
*   **Weights are read from the job as it is now**, never from the stored judgment.
    `requirements_fingerprint` excludes `must_have` and `weight` on purpose, so a
    screening stays current when either changes — and the stored JSON keeps the old
    numbers forever. An implementation that reads them back out of `result` passes
    every other test in this file and silently makes weight edits do nothing.
*   **The order is total.** A list that reshuffles between two identical runs is
    unusable, so tied candidates fall through to their id.
*   **A stale screening is excluded and reported**, not ranked beside answers to a
    question nobody is asking any more.

The pure-function tests need no session and no database, exactly like
`test_judge.py` — `rank_screenings` takes value objects by design.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.jobs import JobContext, run_resume_job, run_screening_job
from app.llm.fake import FakeExtractor, FakeMode
from app.pipeline.evidence import MatchKind
from app.pipeline.judge import requirements_fingerprint
from app.pipeline.prompts import JUDGMENT_PROMPT_VERSION
from app.pipeline.ranking import ScreeningView, rank_screenings
from app.schemas.judgment import Judgment, RequirementJudgment, RequirementSpec, Verdict
from app.schemas.profile import EvidenceRef
from app.schemas.ranking import ExclusionReason
from app.storage import LocalStorage
from tests.conftest import resume_upload
from tests.test_worker import RecordingQueue

# ---------------------------------------------------------------------------
# Builders. A judgment here is written by hand rather than produced by judging:
# these tests are about what happens *after* a verdict exists.
# ---------------------------------------------------------------------------


def spec(label: str, *, must_have: bool = False, weight: float = 1.0) -> RequirementSpec:
    return RequirementSpec(
        id=f"r-{label}", label=label, kind="skill", must_have=must_have, weight=weight
    )


def _evidence(label: str) -> EvidenceRef:
    return EvidenceRef(
        quote=f"{label} in production",
        char_start=0,
        char_end=10,
        page=1,
        match_kind=MatchKind.EXACT,
    )


def judgment_for(
    requirements: list[RequirementSpec],
    met: set[str],
    *,
    stored_weight: float | None = None,
    stored_must_have: bool | None = None,
) -> Judgment:
    """A stored judgment over `requirements`, with `met` the labels that resolved.

    `stored_weight` / `stored_must_have` deliberately overwrite what the judgment
    froze at judging time, so a test can make the stored copy disagree with the
    current job — which is the whole point of `TestWeightsComeFromTheJob`.
    """
    return Judgment(
        requirements=[
            RequirementJudgment(
                requirement_id=item.id,
                label=item.label,
                must_have=stored_must_have if stored_must_have is not None else item.must_have,
                weight=stored_weight if stored_weight is not None else item.weight,
                verdict=Verdict.MET if item.label in met else Verdict.NOT_EVIDENCED,
                evidence=[_evidence(item.label)] if item.label in met else [],
            )
            for item in requirements
        ]
    )


def view(
    screening_id: str,
    requirements: list[RequirementSpec],
    met: set[str],
    *,
    status: str = "completed",
    completed: bool = True,
    requirements_hash: str | None = None,
    prompt_version: str | None = JUDGMENT_PROMPT_VERSION,
    judgment: Judgment | str | None = "auto",
    **judgment_kwargs: object,
) -> ScreeningView:
    if judgment == "auto":
        judgment = judgment_for(requirements, met, **judgment_kwargs)  # type: ignore[arg-type]
    return ScreeningView(
        id=screening_id,
        resume_id=f"resume-{screening_id}",
        status=status,
        completed=completed,
        requirements_hash=(
            requirements_hash
            if requirements_hash is not None
            else requirements_fingerprint(requirements)
        ),
        prompt_version=prompt_version,
        judgment=judgment,  # type: ignore[arg-type]
    )


def rank(views: list[ScreeningView], requirements: list[RequirementSpec]):
    return rank_screenings(
        views,
        requirements,
        requirements_hash=requirements_fingerprint(requirements),
        prompt_version=JUDGMENT_PROMPT_VERSION,
    )


def order(ranking) -> list[str]:
    return [entry.screening_id for entry in ranking.ranked]


# ---------------------------------------------------------------------------


class TestTheMustHaveGate:
    """A hard gate, which is the one thing a weight can never reproduce."""

    def test_a_missing_must_have_outranks_nothing(self):
        """The case the gate exists for: a stronger candidate, gated out.

        `b` meets three of four including a heavier one and would win on score
        alone. It misses the must-have, so it ranks below `a`, which meets only
        the two required.
        """
        requirements = [
            spec("Python", must_have=True),
            spec("SQL"),
            spec("Go", weight=5.0),
            spec("AWS", weight=5.0),
        ]
        ranking = rank(
            [
                view("a", requirements, {"Python", "SQL"}),
                view("b", requirements, {"SQL", "Go", "AWS"}),
            ],
            requirements,
        )

        assert order(ranking) == ["a", "b"]
        assert [entry.gate_passed for entry in ranking.ranked] == [True, False]
        # And the gated candidate genuinely scored higher, or this proves nothing.
        assert ranking.ranked[1].score > ranking.ranked[0].score

    def test_no_must_haves_means_everyone_passes_the_gate(self):
        requirements = [spec("Python"), spec("SQL")]
        ranking = rank([view("a", requirements, set())], requirements)

        assert ranking.ranked[0].gate_passed is True
        assert ranking.ranked[0].must_haves_total == 0

    def test_within_the_failing_tier_fewer_missing_gates_ranks_higher(self):
        """Must-haves count toward the score as well as gating, which is what
        separates "missing one" from "missing all"."""
        requirements = [
            spec("Python", must_have=True),
            spec("SQL", must_have=True),
            spec("Go", must_have=True),
        ]
        ranking = rank(
            [
                view("all-missing", requirements, set()),
                view("one-missing", requirements, {"Python", "SQL"}),
            ],
            requirements,
        )

        assert order(ranking) == ["one-missing", "all-missing"]
        assert all(entry.gate_passed is False for entry in ranking.ranked)

    def test_must_have_counts_are_reported(self):
        requirements = [spec("Python", must_have=True), spec("SQL", must_have=True), spec("Go")]
        ranking = rank([view("a", requirements, {"Python", "Go"})], requirements)

        entry = ranking.ranked[0]
        assert (entry.must_haves_met, entry.must_haves_total) == (1, 2)
        assert (entry.requirements_met, entry.requirements_total) == (2, 3)


class TestTheScore:
    def test_a_heavier_requirement_moves_the_score_further(self):
        requirements = [spec("Python", weight=9.0), spec("SQL", weight=1.0)]
        ranking = rank(
            [
                view("heavy", requirements, {"Python"}),
                view("light", requirements, {"SQL"}),
            ],
            requirements,
        )

        assert order(ranking) == ["heavy", "light"]
        assert ranking.ranked[0].score == 0.9
        assert ranking.ranked[1].score == 0.1

    def test_everything_met_is_one_and_nothing_met_is_zero(self):
        requirements = [spec("Python"), spec("SQL")]
        ranking = rank(
            [view("all", requirements, {"Python", "SQL"}), view("none", requirements, set())],
            requirements,
        )

        assert ranking.ranked[0].score == 1.0
        assert ranking.ranked[1].score == 0.0

    def test_a_job_with_no_requirements_scores_zero_and_passes_the_gate(self):
        """Nothing was asked, so nothing is missing — and the denominator is 0."""
        ranking = rank([view("a", [], set())], [])

        entry = ranking.ranked[0]
        assert entry.score == 0.0
        assert entry.gate_passed is True
        assert entry.requirements_total == 0

    def test_a_job_of_only_must_haves_still_scores(self):
        """The reason must-haves are in the denominator: otherwise it is zero."""
        requirements = [spec("Python", must_have=True), spec("SQL", must_have=True)]
        ranking = rank([view("a", requirements, {"Python"})], requirements)

        assert ranking.ranked[0].score == 0.5


class TestWeightsComeFromTheJob:
    """The decision this module is most likely to lose.

    `must_have` and `weight` are excluded from the fingerprint, so editing either
    leaves every screening current while the stored judgment keeps the old value.
    Ranking must therefore read both from the job — and these are the only tests
    that can tell the difference.
    """

    def test_changing_a_weight_reorders_without_restaging_anything(self):
        judged = [spec("Python", weight=1.0), spec("SQL", weight=1.0)]
        views = [
            view("python-only", judged, {"Python"}),
            view("sql-only", judged, {"SQL"}),
        ]

        # Same requirements, same fingerprint — only the weights moved, so both
        # screenings are still perfectly current.
        reweighted = [spec("Python", weight=1.0), spec("SQL", weight=9.0)]
        assert requirements_fingerprint(judged) == requirements_fingerprint(reweighted)

        before = rank(views, judged)
        after = rank(views, reweighted)

        assert order(before) == ["python-only", "sql-only"]  # tied, split by id
        assert order(after) == ["sql-only", "python-only"]
        assert after.excluded == []

    def test_the_stored_weight_is_ignored_entirely(self):
        """Stored judgments that shout the opposite must not be listened to."""
        requirements = [spec("Python", weight=9.0), spec("SQL", weight=1.0)]
        views = [
            view("python-only", requirements, {"Python"}, stored_weight=1.0),
            view("sql-only", requirements, {"SQL"}, stored_weight=99.0),
        ]

        ranking = rank(views, requirements)

        assert order(ranking) == ["python-only", "sql-only"]
        assert ranking.ranked[0].score == 0.9

    def test_promoting_a_requirement_to_must_have_gates_immediately(self):
        judged = [spec("Python"), spec("SQL")]
        views = [
            view("has-python", judged, {"Python"}, stored_must_have=False),
            view("has-sql", judged, {"SQL"}, stored_must_have=False),
        ]

        gated = [spec("Python", must_have=True), spec("SQL")]
        assert requirements_fingerprint(judged) == requirements_fingerprint(gated)

        ranking = rank(views, gated)

        assert order(ranking) == ["has-python", "has-sql"]
        assert [entry.gate_passed for entry in ranking.ranked] == [True, False]

    def test_the_returned_requirements_carry_the_current_values(self):
        requirements = [spec("Python", must_have=True, weight=4.0)]
        ranking = rank(
            [view("a", requirements, {"Python"}, stored_weight=1.0, stored_must_have=False)],
            requirements,
        )

        returned = ranking.ranked[0].requirements[0]
        assert (returned.weight, returned.must_have) == (4.0, True)
        # …while the verdict and its citation still come from the screening.
        assert returned.verdict is Verdict.MET
        assert returned.evidence[0].quote == "Python in production"


class TestTheRationale:
    def test_every_ranked_entry_carries_its_citations(self):
        """The rationale is the citation list, not the score."""
        requirements = [spec("Python"), spec("SQL")]
        ranking = rank([view("a", requirements, {"Python"})], requirements)

        met, unmet = ranking.ranked[0].requirements
        assert met.verdict is Verdict.MET and met.evidence
        assert unmet.verdict is Verdict.NOT_EVIDENCED and unmet.evidence == []

    def test_nothing_is_asserted_absent(self):
        """`not_evidenced`, never `not_met` — the vocabulary has to survive here too."""
        requirements = [spec("Kubernetes")]
        ranking = rank([view("a", requirements, set())], requirements)

        assert ranking.ranked[0].requirements[0].verdict is Verdict.NOT_EVIDENCED


class TestDeterminism:
    def test_input_order_does_not_change_the_result(self):
        """Two of these tie deliberately.

        With distinct scores any sort at all passes this, because Python's sort is
        stable and there is nothing to be stable *about*. `c` and `d` score the
        same, so reversing the input flips them unless the order is total.
        """
        requirements = [spec("Python"), spec("SQL")]
        views = [
            view("c", requirements, {"Python"}),
            view("a", requirements, {"Python", "SQL"}),
            view("d", requirements, {"SQL"}),
            view("b", requirements, set()),
        ]

        forward = rank(views, requirements)
        backward = rank(list(reversed(views)), requirements)

        assert order(forward) == order(backward) == ["a", "c", "d", "b"]
        assert forward.model_dump() == backward.model_dump()

    def test_tied_candidates_order_by_id(self):
        """Without a total order a refresh reshuffles the list."""
        requirements = [spec("Python")]
        views = [view(name, requirements, {"Python"}) for name in ("zeta", "alpha", "mid")]

        ranking = rank(views, requirements)

        assert order(ranking) == ["alpha", "mid", "zeta"]
        assert {entry.score for entry in ranking.ranked} == {1.0}

    def test_rank_is_one_based_and_dense(self):
        requirements = [spec("Python")]
        views = [view(name, requirements, {"Python"}) for name in ("a", "b", "c")]

        ranking = rank(views, requirements)

        assert [entry.rank for entry in ranking.ranked] == [1, 2, 3]


class TestExclusions:
    """Reported, never silently mixed in and never silently re-run."""

    def test_a_stale_screening_is_excluded(self):
        requirements = [spec("Python")]
        stale = view("old", requirements, {"Python"}, requirements_hash="a-different-question")

        ranking = rank([stale], requirements)

        assert ranking.ranked == []
        assert ranking.excluded[0].reason is ExclusionReason.STALE
        assert ranking.excluded[0].screening_id == "old"

    def test_an_older_prompt_version_is_also_stale(self):
        requirements = [spec("Python")]
        old = view("old", requirements, {"Python"}, prompt_version="judge-v0")

        ranking = rank([old], requirements)

        assert ranking.excluded[0].reason is ExclusionReason.STALE

    @pytest.mark.parametrize("status", ["pending", "processing", "failed", "dead_lettered"])
    def test_anything_without_a_verdict_is_excluded(self, status: str):
        requirements = [spec("Python")]
        unfinished = view("x", requirements, set(), status=status, completed=False, judgment=None)

        ranking = rank([unfinished], requirements)

        assert ranking.ranked == []
        assert ranking.excluded[0].reason is ExclusionReason.NOT_COMPLETED
        assert ranking.excluded[0].status == status

    def test_a_completed_screening_with_no_result_is_malformed(self):
        requirements = [spec("Python")]
        empty = view("x", requirements, set(), judgment=None)

        ranking = rank([empty], requirements)

        assert ranking.excluded[0].reason is ExclusionReason.MALFORMED

    def test_a_requirement_count_mismatch_is_malformed_not_a_bad_join(self):
        """The positional join is only sound on equal lengths, so it is checked."""
        judged = [spec("Python"), spec("SQL")]
        mismatched = view("x", judged, {"Python"}, requirements_hash=None)

        # One requirement now, two in the stored judgment. Contrived — the
        # fingerprint would normally catch it — but joining anyway would attach
        # Python's verdict to a different requirement's weight.
        current = [spec("Python")]
        ranking = rank_screenings(
            [mismatched],
            current,
            requirements_hash=mismatched.requirements_hash or "",
            prompt_version=JUDGMENT_PROMPT_VERSION,
        )

        assert ranking.ranked == []
        assert ranking.excluded[0].reason is ExclusionReason.MALFORMED

    def test_the_fresh_ones_still_rank_around_an_excluded_one(self):
        requirements = [spec("Python")]
        ranking = rank(
            [
                view("fresh", requirements, {"Python"}),
                view("stale", requirements, {"Python"}, requirements_hash="other"),
            ],
            requirements,
        )

        assert order(ranking) == ["fresh"]
        assert [item.screening_id for item in ranking.excluded] == ["stale"]

    def test_nothing_at_all_ranks_to_nothing_at_all(self):
        ranking = rank([], [spec("Python")])
        assert ranking.ranked == [] and ranking.excluded == []


# ---------------------------------------------------------------------------
# Over HTTP. The pure function is covered above; these pin the wiring and the
# ownership rule.
# ---------------------------------------------------------------------------

JOB_PAYLOAD = {
    "title": "Backend Engineer",
    "requirements": [
        {"kind": "skill", "label": "Python", "must_have": True},
        {"kind": "skill", "label": "PostgreSQL", "weight": 1.0},
        {"kind": "skill", "label": "Kubernetes", "weight": 1.0},
    ],
}


@pytest.fixture
async def authed_client(recruiter_client: AsyncClient) -> AsyncClient:
    """This whole module is the recruiter side, so the default client is one."""
    return recruiter_client


@pytest.fixture
def queue() -> RecordingQueue:
    """Replaces the inline queue so a test runs each job deliberately."""
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


async def _completed_screening(
    client: AsyncClient, context: JobContext
) -> tuple[str, str, dict[str, object]]:
    """A job, a parsed resume and one screening run to completion.

    The resume job runs explicitly because `RecordingQueue` replaces the inline
    queue: without it the upload only *queues* work and the screening would be
    `NotScreenable` for a reason that has nothing to do with ranking.
    """
    job = await client.post("/jobs", json=JOB_PAYLOAD)
    assert job.status_code == 201, job.text

    uploaded = await client.post("/resumes", files=resume_upload())
    resume_id = uploaded.json()["id"]
    await run_resume_job(context, uuid.UUID(resume_id))

    created = await client.post(
        f"/jobs/{job.json()['id']}/screenings", json={"resume_id": resume_id}
    )
    assert created.status_code == 202, created.text
    await run_screening_job(context, uuid.UUID(created.json()["id"]))

    return job.json()["id"], created.json()["id"], job.json()


class TestTheRankingRoute:
    async def test_a_completed_screening_is_ranked_with_its_citations(
        self, authed_client: AsyncClient, context: JobContext
    ):
        job_id, screening_id, _ = await _completed_screening(authed_client, context)

        response = await authed_client.get(f"/jobs/{job_id}/ranking")
        assert response.status_code == 200, response.text

        body = response.json()
        assert body["excluded"] == []
        entry = body["ranked"][0]
        assert entry["rank"] == 1
        assert entry["screening_id"] == screening_id
        assert entry["requirements_total"] == 3
        # The rationale travels with the rank rather than needing a second request.
        assert len(entry["requirements"]) == 3

    async def test_changing_a_weight_rescores_without_staling_anything(
        self, authed_client: AsyncClient, context: JobContext
    ):
        """The property the whole design of the fingerprint exists to allow.

        One resume, so this is about the *score* moving rather than the order —
        reordering is covered by `TestWeightsComeFromTheJob` against the pure
        function. What matters over HTTP is that the number moved while the
        screening stayed current and nothing was re-queued.
        """
        job_id, _, job = await _completed_screening(authed_client, context)

        before = (await authed_client.get(f"/jobs/{job_id}/ranking")).json()["ranked"][0]

        requirement = job["requirements"][1]  # type: ignore[index]
        patched = await authed_client.patch(
            f"/jobs/{job_id}/requirements/{requirement['id']}", json={"weight": 20.0}
        )
        assert patched.status_code == 200, patched.text

        after = (await authed_client.get(f"/jobs/{job_id}/ranking")).json()["ranked"][0]

        # Still ranked, still current — only the arithmetic moved.
        assert after["score"] != before["score"]
        listed = (await authed_client.get(f"/jobs/{job_id}/screenings")).json()
        assert listed[0]["is_stale"] is False
        assert listed[0]["attempts"] == 1

    async def test_changing_a_label_excludes_it_as_stale(
        self, authed_client: AsyncClient, context: JobContext
    ):
        job_id, screening_id, job = await _completed_screening(authed_client, context)

        requirement = job["requirements"][1]  # type: ignore[index]
        await authed_client.patch(
            f"/jobs/{job_id}/requirements/{requirement['id']}", json={"label": "Postgres 17"}
        )

        body = (await authed_client.get(f"/jobs/{job_id}/ranking")).json()

        assert body["ranked"] == []
        assert body["excluded"][0]["screening_id"] == screening_id
        assert body["excluded"][0]["reason"] == "stale"

    async def test_another_account_gets_404_not_403(
        self, authed_client: AsyncClient, context: JobContext
    ):
        job_id, _, _ = await _completed_screening(authed_client, context)

        registered = await authed_client.post(
            "/auth/register",
            json={"email": "someone-else@example.com", "password": "correct horse battery"},
        )
        authed_client.headers["Authorization"] = f"Bearer {registered.json()['access_token']}"

        response = await authed_client.get(f"/jobs/{job_id}/ranking")
        assert response.status_code == 404

    async def test_a_job_nobody_has_screened_ranks_to_nothing(self, authed_client: AsyncClient):
        job = await authed_client.post("/jobs", json=JOB_PAYLOAD)

        response = await authed_client.get(f"/jobs/{job.json()['id']}/ranking")

        assert response.status_code == 200
        assert response.json() == {"ranked": [], "excluded": []}
