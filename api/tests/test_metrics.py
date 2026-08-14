"""The usage and quality dashboard (M5 slice 2).

What these pin, in rough order of how quietly they would break:

- **A group's cost is unknown unless every call in it is priced.** `SUM` skips nulls,
  so the naive version reports a partial total as though it were complete — the same
  class of silent corruption as a stale price table.
- **The hallucination rate is recomputed from the totals, not averaged.** Averaging
  per-profile rates weights a one-claim document like a thirty-claim one.
- **The four buckets partition the rows exactly**, so a call that the unenforced
  `resume_id` xor `screening_id` invariant leaves unattributable is reported rather
  than dropped from every total.
- **Scoping is two arms**, because `llm_call_logs` has no owner column: miss one and
  half the calls silently disappear for every non-admin caller.
- **The dashboard spends nothing.**
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Candidate, ExtractedProfileRow, LLMCallLog, Resume, ResumeStatus, Role
from tests.conftest import register_as, resume_upload

pytestmark = pytest.mark.anyio


async def _set_role(sessionmaker: async_sessionmaker[AsyncSession], email: str, role: Role) -> None:
    async with sessionmaker() as session:
        account = (
            await session.execute(select(Candidate).where(Candidate.email == email))
        ).scalar_one()
        account.role = role
        await session.commit()


async def _account_id(sessionmaker: async_sessionmaker[AsyncSession], email: str) -> uuid.UUID:
    async with sessionmaker() as session:
        return (
            await session.execute(select(Candidate.id).where(Candidate.email == email))
        ).scalar_one()


async def _add_resume(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    owner: uuid.UUID,
    status: ResumeStatus = ResumeStatus.EXTRACTED,
) -> uuid.UUID:
    """A resume row without going through the upload path.

    These tests are about arithmetic over stored rows, so they write the rows they
    mean rather than driving a pipeline to produce approximately them.
    """
    async with sessionmaker() as session:
        resume = Resume(
            candidate_id=owner,
            filename="synthetic.pdf",
            content_hash=uuid.uuid4().hex,
            size_bytes=1,
            storage_key=f"synthetic/{uuid.uuid4().hex}",
            status=status,
        )
        session.add(resume)
        await session.commit()
        return resume.id


async def _add_call(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    resume_id: uuid.UUID | None = None,
    screening_id: uuid.UUID | None = None,
    cost_usd: float | None = 0.0,
    input_tokens: int = 10,
    output_tokens: int = 20,
    latency_ms: int = 100,
    prompt_version: str = "extract-v1",
) -> None:
    async with sessionmaker() as session:
        session.add(
            LLMCallLog(
                resume_id=resume_id,
                screening_id=screening_id,
                provider="fake",
                model="rule-based",
                prompt_version=prompt_version,
                attempt=1,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=0,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
            )
        )
        await session.commit()


async def _add_profile(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    resume_id: uuid.UUID,
    verified: int,
    dropped: int,
    attempts: int = 1,
) -> None:
    total = verified + dropped
    async with sessionmaker() as session:
        session.add(
            ExtractedProfileRow(
                resume_id=resume_id,
                profile={},
                claims_verified=verified,
                claims_dropped=dropped,
                # Deliberately the per-row rate, so a test can prove the report does
                # not simply average these.
                hallucination_rate=(dropped / total) if total else 0.0,
                attempts=attempts,
            )
        )
        await session.commit()


async def _usage(client: AsyncClient) -> dict:
    response = await client.get("/metrics/usage")
    assert response.status_code == 200, response.text
    return response.json()


class TestTheEmptyReport:
    async def test_a_new_account_gets_zeroes_rather_than_an_error(self, authed_client: AsyncClient):
        report = await _usage(authed_client)

        assert report["scope"] == "own"
        assert report["totals"]["calls"] == 0
        assert report["by_group"] == []
        assert report["parse_outcomes"] == []
        assert report["quality"]["profiles"] == 0

    async def test_an_empty_rate_is_null_rather_than_zero(self, authed_client: AsyncClient):
        """0.0 would read as "nothing was fabricated", which is a claim about data
        that does not exist."""
        report = await _usage(authed_client)
        assert report["quality"]["hallucination_rate"] is None

    async def test_an_empty_latency_is_null_rather_than_zero(self, authed_client: AsyncClient):
        """0 ms would read as "instant"."""
        assert (await _usage(authed_client))["totals"]["latency_ms_mean"] is None

    async def test_every_bucket_is_present_even_when_empty(self, authed_client: AsyncClient):
        """An absent key and a zero are different claims, and only one says "we
        looked"."""
        buckets = (await _usage(authed_client))["by_bucket"]
        assert set(buckets) == {"extraction", "judging", "unattributed", "ambiguous"}
        assert all(bucket["calls"] == 0 for bucket in buckets.values())


class TestTheRealPath:
    async def test_an_upload_is_counted(self, authed_client: AsyncClient, sessionmaker_for_tests):
        await authed_client.post("/resumes", **resume_upload())

        report = await _usage(authed_client)

        assert report["totals"]["calls"] >= 1
        assert report["by_bucket"]["extraction"]["calls"] >= 1
        assert report["by_bucket"]["judging"]["calls"] == 0
        assert report["quality"]["profiles"] == 1
        assert report["quality"]["claims_verified"] > 0
        assert [outcome["status"] for outcome in report["parse_outcomes"]] == ["extracted"]

    async def test_the_prompt_family_is_named(self, authed_client: AsyncClient):
        """`prompt_version` is the axis that makes the grouping worth showing —
        comparing prompt revisions is guesswork without it."""
        await authed_client.post("/resumes", **resume_upload())

        groups = (await _usage(authed_client))["by_group"]
        assert [group["prompt_version"] for group in groups] == ["extract-v1"]
        assert groups[0]["bucket"] == "extraction"

    async def test_reading_the_dashboard_spends_nothing(
        self, authed_client: AsyncClient, sessionmaker_for_tests
    ):
        """The rule the whole slice is built to keep: it reports, it never re-asks."""
        await authed_client.post("/resumes", **resume_upload())

        async with sessionmaker_for_tests() as session:
            before = (await session.execute(select(func.count()).select_from(LLMCallLog))).scalar()

        for _ in range(3):
            await _usage(authed_client)

        async with sessionmaker_for_tests() as session:
            after = (await session.execute(select(func.count()).select_from(LLMCallLog))).scalar()

        assert after == before


class TestCostIsNeverPartiallyReported:
    async def test_a_fully_priced_group_reports_its_cost(
        self, authed_client: AsyncClient, sessionmaker_for_tests
    ):
        owner = await _account_id(sessionmaker_for_tests, "candidate@example.com")
        resume = await _add_resume(sessionmaker_for_tests, owner=owner)
        await _add_call(sessionmaker_for_tests, resume_id=resume, cost_usd=0.25)
        await _add_call(sessionmaker_for_tests, resume_id=resume, cost_usd=0.75)

        totals = (await _usage(authed_client))["totals"]

        assert totals["calls"] == 2
        assert totals["calls_priced"] == 2
        assert totals["cost_usd"] == pytest.approx(1.0)

    async def test_one_unpriced_call_makes_the_whole_total_unknown(
        self, authed_client: AsyncClient, sessionmaker_for_tests
    ):
        """The rule `cost_usd`'s nullability exists for, at the aggregate grain.

        SQL `SUM` skips nulls, so the obvious implementation reports 0.25 here — a
        number that looks complete, is not, and gives nobody a reason to doubt it. A
        missing total is visibly missing; a partial one is not.
        """
        owner = await _account_id(sessionmaker_for_tests, "candidate@example.com")
        resume = await _add_resume(sessionmaker_for_tests, owner=owner)
        await _add_call(sessionmaker_for_tests, resume_id=resume, cost_usd=0.25)
        await _add_call(sessionmaker_for_tests, resume_id=resume, cost_usd=None)

        totals = (await _usage(authed_client))["totals"]

        assert totals["calls"] == 2
        assert totals["calls_priced"] == 1, "the reader must be able to see why it is unknown"
        assert totals["cost_usd"] is None

    async def test_an_unknown_cost_is_contagious_upward(
        self, authed_client: AsyncClient, sessionmaker_for_tests
    ):
        """A priced group and an unpriced one must not sum to the priced one's number."""
        owner = await _account_id(sessionmaker_for_tests, "candidate@example.com")
        resume = await _add_resume(sessionmaker_for_tests, owner=owner)
        await _add_call(sessionmaker_for_tests, resume_id=resume, cost_usd=0.5)
        await _add_call(
            sessionmaker_for_tests, resume_id=resume, cost_usd=None, prompt_version="judge-v1"
        )

        report = await _usage(authed_client)
        priced = next(g for g in report["by_group"] if g["prompt_version"] == "extract-v1")

        assert priced["totals"]["cost_usd"] == pytest.approx(0.5)
        assert report["totals"]["cost_usd"] is None


class TestTheHallucinationRate:
    async def test_it_is_computed_from_the_totals_not_averaged(
        self, authed_client: AsyncClient, sessionmaker_for_tests
    ):
        """Two profiles of very different sizes, chosen so the two formulas disagree.

        Profile A: 1 verified, 1 dropped -> its own rate is 0.5
        Profile B: 98 verified, 0 dropped -> its own rate is 0.0
        The mean of the per-profile rates is 0.25. The truth is 1/100 = 0.01.
        Averaging rates would report this account as 25x more unreliable than it is.
        """
        owner = await _account_id(sessionmaker_for_tests, "candidate@example.com")
        first = await _add_resume(sessionmaker_for_tests, owner=owner)
        second = await _add_resume(sessionmaker_for_tests, owner=owner)
        await _add_profile(sessionmaker_for_tests, resume_id=first, verified=1, dropped=1)
        await _add_profile(sessionmaker_for_tests, resume_id=second, verified=98, dropped=0)

        quality = (await _usage(authed_client))["quality"]

        assert quality["claims_verified"] == 99
        assert quality["claims_dropped"] == 1
        assert quality["hallucination_rate"] == pytest.approx(0.01)
        assert quality["hallucination_rate"] != pytest.approx(0.25)

    async def test_attempts_come_from_the_stats_not_the_job_counter(
        self, authed_client: AsyncClient, sessionmaker_for_tests
    ):
        """`ExtractedProfileRow.attempts` counts model calls; `Resume.attempts` is the
        job counter. They are spelled the same and mean different things."""
        owner = await _account_id(sessionmaker_for_tests, "candidate@example.com")
        resume = await _add_resume(sessionmaker_for_tests, owner=owner)
        await _add_profile(
            sessionmaker_for_tests, resume_id=resume, verified=3, dropped=0, attempts=4
        )

        assert (await _usage(authed_client))["quality"]["extraction_attempts_total"] == 4


class TestTheBucketsPartitionTheRows:
    async def test_the_buckets_sum_to_the_total(
        self, authed_client: AsyncClient, sessionmaker_for_tests
    ):
        owner = await _account_id(sessionmaker_for_tests, "candidate@example.com")
        resume = await _add_resume(sessionmaker_for_tests, owner=owner)
        for _ in range(3):
            await _add_call(sessionmaker_for_tests, resume_id=resume)

        report = await _usage(authed_client)

        assert sum(b["calls"] for b in report["by_bucket"].values()) == report["totals"]["calls"]
        assert sum(g["totals"]["calls"] for g in report["by_group"]) == report["totals"]["calls"]

    async def test_an_unattributable_call_is_reported_rather_than_lost(
        self, client: AsyncClient, sessionmaker_for_tests
    ):
        """`resume_id` xor `screening_id` is a docstring, not a constraint, so a row
        with neither is legal. It has no owner, so only an admin can see it — and it
        must appear as `unattributed` rather than as a hole in the total.
        """
        await register_as(client, email="boss@example.com")
        await _set_role(sessionmaker_for_tests, "boss@example.com", Role.ADMIN)
        await _add_call(sessionmaker_for_tests, resume_id=None, screening_id=None)

        report = await _usage(client)

        assert report["scope"] == "all"
        assert report["by_bucket"]["unattributed"]["calls"] == 1
        assert report["totals"]["calls"] == 1
        assert sum(b["calls"] for b in report["by_bucket"].values()) == 1


class TestScope:
    async def test_an_account_does_not_see_another_accounts_calls(
        self, client: AsyncClient, sessionmaker_for_tests
    ):
        await register_as(client, email="first@example.com")
        await client.post("/resumes", **resume_upload())
        mine = await _usage(client)

        await register_as(client, email="second@example.com")
        theirs = await _usage(client)

        assert mine["totals"]["calls"] >= 1
        assert theirs["totals"]["calls"] == 0
        assert theirs["quality"]["profiles"] == 0
        assert theirs["parse_outcomes"] == []

    async def test_an_admin_sees_every_row(self, client: AsyncClient, sessionmaker_for_tests):
        """Decided with the owner on 2026-08-15. Note this is a row scope: it works
        because the role is read in the WHERE clause, not because a route was gated —
        `require_role` could not have produced it."""
        await register_as(client, email="worker@example.com")
        await client.post("/resumes", **resume_upload())

        await register_as(client, email="boss@example.com")
        assert (await _usage(client))["totals"]["calls"] == 0, "not an admin yet"

        await _set_role(sessionmaker_for_tests, "boss@example.com", Role.ADMIN)
        report = await _usage(client)

        assert report["scope"] == "all"
        assert report["totals"]["calls"] >= 1
        assert report["quality"]["profiles"] == 1

    async def test_a_judging_call_reaches_its_owner_through_the_other_arm(
        self, client: AsyncClient, sessionmaker_for_tests
    ):
        """The scoping bug that would be invisible with one join.

        A judging call carries `screening_id` and no `resume_id`, so it reaches its
        owner through `screenings -> jobs.owner_id`. An implementation that scoped on
        `resumes.candidate_id` alone would pass every extraction test and silently
        report zero judging calls for everyone.
        """
        recruiter = await register_as(client, email="hirer@example.com", role="recruiter")
        upload = await recruiter.post("/resumes", **resume_upload())
        resume_id = upload.json()["id"]

        created = await recruiter.post(
            "/jobs",
            json={"title": "Backend", "requirements": [{"kind": "skill", "label": "Python"}]},
        )
        job_id = created.json()["id"]
        screened = await recruiter.post(f"/jobs/{job_id}/screenings", json={"resume_id": resume_id})
        assert screened.status_code in (200, 202), screened.text

        report = await _usage(recruiter)

        assert report["by_bucket"]["judging"]["calls"] >= 1, (
            "a judging call must reach its owner through screenings -> jobs.owner_id"
        )
        assert report["by_bucket"]["extraction"]["calls"] >= 1
        assert report["by_bucket"]["judging"]["calls"] != report["totals"]["calls"], (
            "the extraction/judging split must not be collapsed"
        )


class TestAuth:
    async def test_it_needs_a_token(self, client: AsyncClient):
        assert (await client.get("/metrics/usage")).status_code == 401

    async def test_every_role_may_read_its_own(self, recruiter_client: AsyncClient):
        """No `require_role` here on purpose: gating the route on ADMIN would 403 the
        very accounts that own the rows."""
        assert (await _usage(recruiter_client))["scope"] == "own"


class TestOrdering:
    async def test_groups_are_ordered_by_call_count_with_a_total_tie_break(
        self, authed_client: AsyncClient, sessionmaker_for_tests
    ):
        """A list that reshuffles between identical requests is the lesson
        `test_ranking.py` paid for."""
        owner = await _account_id(sessionmaker_for_tests, "candidate@example.com")
        resume = await _add_resume(sessionmaker_for_tests, owner=owner)
        await _add_call(sessionmaker_for_tests, resume_id=resume, prompt_version="extract-v1")
        for _ in range(2):
            await _add_call(sessionmaker_for_tests, resume_id=resume, prompt_version="judge-v1")

        first = await _usage(authed_client)
        second = await _usage(authed_client)

        versions = [group["prompt_version"] for group in first["by_group"]]
        assert versions == ["judge-v1", "extract-v1"], "most calls first"
        assert first["by_group"] == second["by_group"], "identical requests, identical order"
