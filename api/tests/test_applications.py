"""Applying to a job, and every move an application may or may not make.

Two halves, and the split is the same one `test_ranking.py` makes. The first is
pure — `app/applications.py` takes facts and returns a decision, so the whole rule
set is exercised with no session, no HTTP and no fixtures. The second drives it
through the routes, where the interesting question is not the rules but whether the
row and the log stay in step.

**The property this module exists to hold:** `Application.state` is a projection of
`application_events`, and replaying the log has to reproduce it. If the two ever
disagree, the column is the one that is wrong — a state nobody can account for is
exactly what an append-only log is here to prevent.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.applications import (
    SYSTEM,
    Actor,
    Mover,
    Refused,
    Transition,
    plan_transition,
    replay,
)
from app.models import Role
from app.models.application import ApplicationState as S
from tests.conftest import publish_job, register_as, resume_upload

JOB = {
    "title": "Backend Engineer",
    "requirements": [{"kind": "skill", "label": "Python"}, {"kind": "skill", "label": "SQL"}],
}

APPLICANT = Actor(Mover.APPLICANT, Role.CANDIDATE, uuid.uuid4())
OWNER = Actor(Mover.JOB_OWNER, Role.RECRUITER, uuid.uuid4())


def _allowed(result: Transition | Refused) -> Transition:
    assert isinstance(result, Transition), getattr(result, "why", result)
    return result


def _refused(result: Transition | Refused) -> Refused:
    assert isinstance(result, Refused), f"expected a refusal, got {result}"
    return result


class TestWhoMayMoveWhat:
    """The rules, with no database anywhere near them."""

    def test_an_owner_shortlists_a_screened_application(self):
        move = _allowed(plan_transition(S.SCREENED, S.SHORTLISTED, actor=OWNER, screening_id="s-1"))
        assert move.to_state is S.SHORTLISTED
        assert move.screening_id == "s-1"

    def test_an_applicant_may_not_shortlist_themselves(self):
        refusal = _refused(
            plan_transition(S.SCREENED, S.SHORTLISTED, actor=APPLICANT, screening_id="s-1")
        )
        assert "not by the applicant" in refusal.why

    def test_an_owner_may_not_withdraw_on_someone_s_behalf(self):
        """Withdrawing is the applicant's word about themselves."""
        refusal = _refused(plan_transition(S.APPLIED, S.WITHDRAWN, actor=OWNER))
        assert "not by the job_owner" in refusal.why

    def test_the_system_never_gets_an_opinion(self):
        """A worker follows a screening. It does not shortlist or reject anybody."""
        for state in (S.SHORTLISTED, S.REJECTED):
            _refused(
                plan_transition(
                    S.SCREENED, state, actor=SYSTEM, reason="because", screening_id="s-1"
                )
            )

    @pytest.mark.parametrize("state", [S.REJECTED, S.WITHDRAWN])
    def test_a_terminal_application_cannot_be_moved_again(self, state: S):
        refusal = _refused(plan_transition(state, S.SHORTLISTED, actor=OWNER, screening_id="s"))
        assert "cannot be moved again" in refusal.why

    def test_moving_to_where_it_already_is_is_refused_rather_than_logged(self):
        """An event recording that nothing happened would make the log lie."""
        refusal = _refused(plan_transition(S.APPLIED, S.APPLIED, actor=APPLICANT))
        assert "already applied" in refusal.why

    def test_every_state_has_a_row_in_the_table(self):
        """A state added without its rules would otherwise be silently immovable."""
        for state in S:
            plan_transition(state, S.WITHDRAWN, actor=APPLICANT)


class TestTheEvidenceRule:
    """A shortlist is a claim about a person, so it must rest on something."""

    def test_shortlisting_before_a_screening_is_refused(self):
        refusal = _refused(plan_transition(S.APPLIED, S.SHORTLISTED, actor=OWNER))
        assert "only be shortlisted once it has been screened" in refusal.why

    def test_shortlisting_without_naming_the_screening_is_refused(self):
        """Belt and braces over the state table, on purpose.

        Reaching `shortlisted` already requires coming from `screened`, so this is
        unreachable today — and it is the guarantee, not the path, that matters. A
        future edit to the table must not be able to lose it.
        """
        refusal = _refused(
            plan_transition(S.SCREENED, S.SHORTLISTED, actor=OWNER, screening_id=None)
        )
        assert "needs a completed screening" in refusal.why

    def test_rejecting_needs_a_reason(self):
        assert (
            "needs a reason" in _refused(plan_transition(S.SCREENED, S.REJECTED, actor=OWNER)).why
        )
        assert (
            "needs a reason"
            in _refused(plan_transition(S.SCREENED, S.REJECTED, actor=OWNER, reason="   ")).why
        )

    def test_a_reason_is_kept_and_trimmed(self):
        move = _allowed(
            plan_transition(S.SCREENED, S.REJECTED, actor=OWNER, reason="  not enough Go  ")
        )
        assert move.reason == "not enough Go"

    def test_withdrawing_needs_no_reason(self):
        """The candidate owes nobody an explanation for leaving."""
        assert _allowed(plan_transition(S.SCREENED, S.WITHDRAWN, actor=APPLICANT)).reason is None


class TestResolvingAnActor:
    def test_an_admin_is_treated_as_the_job_owner(self):
        actor = Actor.of(
            Role.ADMIN, account_id=uuid.uuid4(), is_applicant=False, is_job_owner=False
        )
        assert actor is not None and actor.mover is Mover.JOB_OWNER

    def test_a_stranger_is_nobody(self):
        assert (
            Actor.of(
                Role.RECRUITER, account_id=uuid.uuid4(), is_applicant=False, is_job_owner=False
            )
            is None
        )

    def test_owning_the_job_wins_over_being_the_applicant(self):
        """Someone who applied to their own posting gets the wider of the two."""
        actor = Actor.of(
            Role.RECRUITER, account_id=uuid.uuid4(), is_applicant=True, is_job_owner=True
        )
        assert actor is not None and actor.mover is Mover.JOB_OWNER

    def test_every_resolved_actor_carries_its_account(self):
        """The bug a live run found and no test did.

        `actor_id` used to be derived from the mover, and the job owner's id is not
        on the application — so every recruiter decision was written to the audit log
        as though the system had made it. `actor_role` was set correctly, which is
        exactly what made the old assertion pass.
        """
        account = uuid.uuid4()
        for kwargs in (
            {"is_applicant": True, "is_job_owner": False},
            {"is_applicant": False, "is_job_owner": True},
        ):
            actor = Actor.of(Role.RECRUITER, account_id=account, **kwargs)
            assert actor is not None and actor.account_id == account

    def test_the_system_carries_no_account(self):
        assert SYSTEM.account_id is None and SYSTEM.role is None


class TestReplay:
    def test_a_log_replays_to_its_final_state(self):
        assert (
            replay([(None, S.APPLIED), (S.APPLIED, S.SCREENING), (S.SCREENING, S.SCREENED)])
            is S.SCREENED
        )

    def test_a_log_with_a_gap_replays_to_nothing(self):
        """The check has to be able to fail, or it proves nothing about the column."""
        assert replay([(None, S.APPLIED), (S.SCREENED, S.SHORTLISTED)]) is None

    def test_an_empty_log_is_no_state(self):
        assert replay([]) is None


async def _apply(client: AsyncClient) -> dict[str, str]:
    """A recruiter with a job, an applicant with a resume, and an application."""
    await register_as(client, email="hirer@example.com", role="recruiter")
    job_id = (await client.post("/jobs", json=JOB)).json()["id"]
    await publish_job(client, job_id=job_id, as_email="hirer@example.com")
    recruiter = client.headers["Authorization"]

    await register_as(client, email="seeker@example.com")
    applicant = client.headers["Authorization"]
    applicant_id = (await client.get("/auth/me")).json()["id"]
    resume_id = (await client.post("/resumes", **resume_upload())).json()["id"]

    created = await client.post(f"/jobs/{job_id}/applications", json={"resume_id": resume_id})
    assert created.status_code == 201, created.text
    return {
        "job": job_id,
        "resume": resume_id,
        "application": created.json()["id"],
        "recruiter": recruiter,
        "applicant": applicant,
        "applicant_id": applicant_id,
    }


async def _states(client: AsyncClient, application_id: str) -> list[str]:
    events = await client.get(f"/applications/{application_id}/events")
    assert events.status_code == 200, events.text
    return [event["to_state"] for event in events.json()]


class TestApplying:
    async def test_applying_creates_the_row_and_its_first_event(self, client: AsyncClient):
        ids = await _apply(client)
        assert await _states(client, ids["application"]) == ["applied"]

        events = (await client.get(f"/applications/{ids['application']}/events")).json()
        assert events[0]["from_state"] is None, "the first event records being made, not moved"
        assert events[0]["actor_id"] == ids["applicant_id"]
        # Every entry says what its author was at the time, including the first.
        assert events[0]["actor_role"] == "candidate"

    async def test_applying_twice_is_the_same_application(self, client: AsyncClient):
        """Natural-key idempotency: 201 then 200, no second row, no second event."""
        ids = await _apply(client)
        again = await client.post(
            f"/jobs/{ids['job']}/applications", json={"resume_id": ids["resume"]}
        )
        assert again.status_code == 200
        assert again.json()["id"] == ids["application"]
        assert await _states(client, ids["application"]) == ["applied"]

    async def test_applying_with_someone_elses_resume_is_not_found(self, client: AsyncClient):
        ids = await _apply(client)
        stranger_resume = ids["resume"]

        await register_as(client, email="thief@example.com")
        response = await client.post(
            f"/jobs/{ids['job']}/applications", json={"resume_id": stranger_resume}
        )
        assert response.status_code == 404

    async def test_a_recruiter_may_apply_too(self, client: AsyncClient):
        """A role says which routes you may reach, not which life you may lead."""
        ids = await _apply(client)
        await register_as(client, email="alsohiring@example.com", role="recruiter")
        resume_id = (await client.post("/resumes", **resume_upload())).json()["id"]

        response = await client.post(
            f"/jobs/{ids['job']}/applications", json={"resume_id": resume_id}
        )
        assert response.status_code == 201

    async def test_the_filename_comes_from_the_server(self, client: AsyncClient):
        """The recruiter cannot join it from `GET /resumes` — it is not theirs."""
        ids = await _apply(client)
        client.headers["Authorization"] = ids["recruiter"]

        listed = (await client.get(f"/jobs/{ids['job']}/applications")).json()
        assert [row["resume_filename"] for row in listed] == ["resume_en.pdf"]
        assert (await client.get("/resumes")).json() == [], "and it is not in their own list"

    async def test_the_resume_status_comes_from_the_server_too(self, client: AsyncClient):
        """For the same reason, and it is what says whether it can be screened.

        A recruiter may screen an applicant's resume but cannot list it, so without
        this the applicants panel could not tell a resume it can screen from one
        that would raise `NotScreenable` on the worker — and it offered neither.
        Applying does not require an extracted resume, so this is a real question
        rather than a constant that could be assumed.
        """
        ids = await _apply(client)
        client.headers["Authorization"] = ids["recruiter"]

        listed = (await client.get(f"/jobs/{ids['job']}/applications")).json()
        assert [row["resume_status"] for row in listed] == ["extracted"]


class TestMovingAnApplication:
    async def test_the_screening_journey_moves_it_without_anyone_asking(self, client: AsyncClient):
        """`screening` then `screened` are derived from the `Screening` row.

        The system claims `screened` only because a screening completed, and the
        event names which one. That is the milestone's rule with a body.
        """
        ids = await _apply(client)
        client.headers["Authorization"] = ids["recruiter"]

        queued = await client.post(
            f"/jobs/{ids['job']}/screenings", json={"resume_id": ids["resume"]}
        )
        assert queued.status_code in (200, 202), queued.text

        # The inline queue runs the job before the response, so both moves have
        # happened by now.
        assert await _states(client, ids["application"]) == [
            "applied",
            "screening",
            "screened",
        ]

        events = (await client.get(f"/applications/{ids['application']}/events")).json()
        screened = events[-1]
        assert screened["actor_id"] is None, "a worker is not a person"
        assert screened["screening_id"], "and it names what it rested on"

    async def test_shortlisting_needs_the_screening_to_have_happened(self, client: AsyncClient):
        ids = await _apply(client)
        client.headers["Authorization"] = ids["recruiter"]

        too_early = await client.post(
            f"/applications/{ids['application']}/transitions",
            json={"to_state": "shortlisted"},
        )
        assert too_early.status_code == 409
        assert "screened" in too_early.json()["detail"]

        await client.post(f"/jobs/{ids['job']}/screenings", json={"resume_id": ids["resume"]})
        now = await client.post(
            f"/applications/{ids['application']}/transitions",
            json={"to_state": "shortlisted"},
        )
        assert now.status_code == 200
        assert now.json()["state"] == "shortlisted"

        events = (await client.get(f"/applications/{ids['application']}/events")).json()
        assert events[-1]["screening_id"], "the shortlist records the evidence it rests on"
        assert events[-1]["actor_role"] == "recruiter"
        # And *who*, not just what role. Asserting the role alone is what let a
        # recruiter's decision be logged as the system's for a whole live run.
        me = (await client.get("/auth/me")).json()["id"]
        assert events[-1]["actor_id"] == me
        assert [e["actor_id"] for e in events] == [
            ids["applicant_id"],
            None,
            None,
            me,
        ], "the system's moves are anonymous and the people's are not"

    async def test_rejecting_without_a_reason_is_refused(self, client: AsyncClient):
        ids = await _apply(client)
        client.headers["Authorization"] = ids["recruiter"]

        refused = await client.post(
            f"/applications/{ids['application']}/transitions", json={"to_state": "rejected"}
        )
        assert refused.status_code == 409
        assert "needs a reason" in refused.json()["detail"]

        accepted = await client.post(
            f"/applications/{ids['application']}/transitions",
            json={"to_state": "rejected", "reason": "looking for more Go experience"},
        )
        assert accepted.status_code == 200
        events = (await client.get(f"/applications/{ids['application']}/events")).json()
        assert events[-1]["reason"] == "looking for more Go experience"

    async def test_an_applicant_may_withdraw_and_a_recruiter_may_not(self, client: AsyncClient):
        ids = await _apply(client)

        client.headers["Authorization"] = ids["recruiter"]
        assert (
            await client.post(
                f"/applications/{ids['application']}/transitions", json={"to_state": "withdrawn"}
            )
        ).status_code == 409

        client.headers["Authorization"] = ids["applicant"]
        assert (
            await client.post(
                f"/applications/{ids['application']}/transitions", json={"to_state": "withdrawn"}
            )
        ).status_code == 200

    async def test_a_withdrawal_outranks_the_worker(self, client: AsyncClient):
        """A candidate who left is not dragged back by a screening completing.

        `follow_screening` finds the move refused and does nothing, rather than
        overruling a person's decision with bookkeeping.
        """
        ids = await _apply(client)
        client.headers["Authorization"] = ids["applicant"]
        await client.post(
            f"/applications/{ids['application']}/transitions", json={"to_state": "withdrawn"}
        )

        client.headers["Authorization"] = ids["recruiter"]
        screened = await client.post(
            f"/jobs/{ids['job']}/screenings", json={"resume_id": ids["resume"]}
        )
        assert screened.status_code in (200, 202), "the screening itself still runs"

        assert await _states(client, ids["application"]) == ["applied", "withdrawn"]

    async def test_a_stranger_sees_no_application_at_all(self, client: AsyncClient):
        """404, not 403 — the id must not be confirmed to someone uninvolved."""
        ids = await _apply(client)
        await register_as(client, email="nobody@example.com", role="recruiter")

        assert (await client.get(f"/applications/{ids['application']}")).status_code == 404
        assert (await client.get(f"/applications/{ids['application']}/events")).status_code == 404
        assert (
            await client.post(
                f"/applications/{ids['application']}/transitions", json={"to_state": "withdrawn"}
            )
        ).status_code == 404


class TestTheLogIsTheRecord:
    async def test_replaying_the_events_reproduces_the_state(self, client: AsyncClient):
        """The one property that makes the column a projection rather than a fact."""
        ids = await _apply(client)
        client.headers["Authorization"] = ids["recruiter"]
        await client.post(f"/jobs/{ids['job']}/screenings", json={"resume_id": ids["resume"]})
        await client.post(
            f"/applications/{ids['application']}/transitions", json={"to_state": "shortlisted"}
        )

        events = (await client.get(f"/applications/{ids['application']}/events")).json()
        stored = (await client.get(f"/applications/{ids['application']}")).json()["state"]

        assert [e["position"] for e in events] == [0, 1, 2, 3], "0-based and gapless"

        pairs = [
            (S(e["from_state"]) if e["from_state"] else None, S(e["to_state"])) for e in events
        ]
        assert replay(pairs) is S(stored)
        assert len(events) == 4, "applied, screening, screened, shortlisted"

    async def test_a_refused_move_writes_no_event(self, client: AsyncClient):
        """A refusal is a decision, not a state change, and must leave no trace."""
        ids = await _apply(client)
        client.headers["Authorization"] = ids["recruiter"]

        before = await _states(client, ids["application"])
        await client.post(
            f"/applications/{ids['application']}/transitions", json={"to_state": "shortlisted"}
        )
        assert await _states(client, ids["application"]) == before


class TestWhatARecruiterMaySeeOfAnApplicant:
    async def test_an_applied_resume_becomes_readable(self, client: AsyncClient):
        """The `_owned_resume` widening, and the 404 it starts from.

        Both halves in one test on purpose: "a recruiter can read this" means
        nothing without "and could not a moment ago".
        """
        await register_as(client, email="hirer2@example.com", role="recruiter")
        job_id = (await client.post("/jobs", json=JOB)).json()["id"]
        await publish_job(client, job_id=job_id, as_email="hirer2@example.com")
        recruiter = client.headers["Authorization"]

        await register_as(client, email="seeker2@example.com")
        applicant = client.headers["Authorization"]
        resume_id = (await client.post("/resumes", **resume_upload())).json()["id"]

        client.headers["Authorization"] = recruiter
        assert (await client.get(f"/resumes/{resume_id}")).status_code == 404

        client.headers["Authorization"] = applicant
        await client.post(f"/jobs/{job_id}/applications", json={"resume_id": resume_id})

        client.headers["Authorization"] = recruiter
        readable = await client.get(f"/resumes/{resume_id}")
        assert readable.status_code == 200
        assert readable.json()["resume"]["filename"] == "resume_en.pdf"

    async def test_but_not_the_controls_for_it(self, client: AsyncClient):
        """Being shown a CV is not being handed the buttons on it.

        Replaying an extraction spends a model call billed to the resume and belongs
        to whoever uploaded it.
        """
        ids = await _apply(client)
        client.headers["Authorization"] = ids["recruiter"]
        assert (await client.post(f"/resumes/{ids['resume']}/retry")).status_code == 404

    async def test_an_unrelated_recruiter_still_sees_nothing(self, client: AsyncClient):
        ids = await _apply(client)
        await register_as(client, email="rival2@example.com", role="recruiter")
        assert (await client.get(f"/resumes/{ids['resume']}")).status_code == 404


class TestTheRankingCarriesTheFilename:
    async def test_a_ranking_names_the_resume_it_ranked(self, client: AsyncClient):
        """`GET /resumes` returns the caller's own, which no longer covers the list."""
        ids = await _apply(client)
        client.headers["Authorization"] = ids["recruiter"]
        await client.post(f"/jobs/{ids['job']}/screenings", json={"resume_id": ids["resume"]})

        ranking = (await client.get(f"/jobs/{ids['job']}/ranking")).json()
        assert ranking["ranked"], ranking
        assert ranking["ranked"][0]["resume_filename"] == "resume_en.pdf"


class TestApplyingToAJobThatIsGone:
    async def test_an_unknown_job_is_not_found(self, client: AsyncClient):
        await register_as(client, email="lost@example.com")
        resume_id = (await client.post("/resumes", **resume_upload())).json()["id"]
        response = await client.post(
            f"/jobs/{uuid.uuid4()}/applications", json={"resume_id": resume_id}
        )
        assert response.status_code == 404


class TestTheReceipt:
    """`GET /applications/{id}/screening` — the route this project was founded on.

    `README.md` names the pain point as candidates rejected by automated screening
    with no explanation. Every screen before this one served the side doing the
    rejecting, so these tests are less about a payload than about who may see one.
    """

    async def _screened(self, client: AsyncClient) -> dict[str, str]:
        ids = await _apply(client)
        client.headers["Authorization"] = ids["recruiter"]
        queued = await client.post(
            f"/jobs/{ids['job']}/screenings", json={"resume_id": ids["resume"]}
        )
        assert queued.status_code in (200, 202), queued.text
        client.headers["Authorization"] = ids["applicant"]
        return ids

    async def test_the_applicant_sees_the_verdicts_and_their_citations(self, client: AsyncClient):
        ids = await self._screened(client)

        response = await client.get(f"/applications/{ids['application']}/screening")
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["job_title"] == JOB["title"]
        assert body["state"] == "screened"
        assert body["requirements"], "a screening with no requirements is not a receipt"
        assert body["document_text"], "an offset with nothing to index into cannot be shown"

        for requirement in body["requirements"]:
            assert requirement["verdict"] in {"met", "not_evidenced"}
            for citation in requirement["evidence"]:
                start, end = citation["char_start"], citation["char_end"]
                # The whole idea, checked from the applicant's side for the first
                # time: the quote is not searched for, it is at these offsets.
                assert body["document_text"][start:end] == citation["quote"]

    async def test_no_weight_and_no_score_reach_the_applicant(self, client: AsyncClient):
        """A weight never reached the judge and a score only means something beside
        other candidates. Neither belongs on a document about one person."""
        ids = await self._screened(client)

        body = (await client.get(f"/applications/{ids['application']}/screening")).json()
        assert "score" not in body
        for requirement in body["requirements"]:
            assert "weight" not in requirement
            assert "must_have" in requirement, "what you were measured on is not a secret"

    async def test_the_recruiter_sees_it_too(self, client: AsyncClient):
        """Both parties to an application, which is what `_visible_application` means."""
        ids = await self._screened(client)
        client.headers["Authorization"] = ids["recruiter"]

        assert (
            await client.get(f"/applications/{ids['application']}/screening")
        ).status_code == 200

    async def test_a_stranger_gets_404_not_403(self, client: AsyncClient):
        """403 on an id confirms the id exists. The same rule as `_owned_job`."""
        ids = await self._screened(client)
        await register_as(client, email="nosy@example.com")

        response = await client.get(f"/applications/{ids['application']}/screening")
        assert response.status_code == 404

    async def test_an_unscreened_application_is_404_too(self, client: AsyncClient):
        """Not 204 and not an empty receipt. "Nothing found yet" and "nothing found
        in your document" are different sentences, and one of them is a claim."""
        ids = await _apply(client)
        client.headers["Authorization"] = ids["applicant"]

        response = await client.get(f"/applications/{ids['application']}/screening")
        assert response.status_code == 404

    async def test_the_labels_are_the_ones_that_were_judged(self, client: AsyncClient):
        """Editing the posting must not relabel a verdict already shown.

        The receipt reads `RequirementJudgment.label`, stored at judging time. A join
        back to the posting's rows would answer this differently, which is the whole
        reason it does not.
        """
        ids = await self._screened(client)
        before = (await client.get(f"/applications/{ids['application']}/screening")).json()
        labels_before = [item["label"] for item in before["requirements"]]
        assert before["posting_changed_since"] is False

        client.headers["Authorization"] = ids["recruiter"]
        requirements = (await client.get(f"/jobs/{ids['job']}")).json()["requirements"]
        patched = await client.patch(
            f"/jobs/{ids['job']}/requirements/{requirements[0]['id']}",
            json={"label": "Rust"},
        )
        assert patched.status_code == 200, patched.text

        client.headers["Authorization"] = ids["applicant"]
        after = (await client.get(f"/applications/{ids['application']}/screening")).json()
        assert [item["label"] for item in after["requirements"]] == labels_before
        assert after["posting_changed_since"] is True, "and it says so rather than hiding it"

    async def test_a_rejection_carries_its_reason(self, client: AsyncClient):
        ids = await self._screened(client)
        client.headers["Authorization"] = ids["recruiter"]
        rejected = await client.post(
            f"/applications/{ids['application']}/transitions",
            json={"to_state": "rejected", "reason": "looking for more Go experience"},
        )
        assert rejected.status_code == 200, rejected.text

        client.headers["Authorization"] = ids["applicant"]
        body = (await client.get(f"/applications/{ids['application']}/screening")).json()
        assert body["state"] == "rejected"
        assert body["reason"] == "looking for more Go experience"
