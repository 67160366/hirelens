"""Screening a resume against a job posting.

Creation is nested under the job (`POST /jobs/{job_id}/screenings`) for the same
reason requirement routes are: ownership is settled in one place, and a screening
is never reachable by guessing an id alone. Reading one is flat
(`GET /screenings/{id}`) because a client that already holds the id should not have
to remember which job it came from — ownership is still checked, through the job.

Both the job and the resume must belong to the caller. That is M3's rule, and M4's
RBAC widens *who* without changing the shape: a recruiter will screen a candidate's
resume against their own posting, and the check becomes "may this actor see both"
rather than "does this actor own both".

Every miss answers **404, not 403**, matching `_owned_job` and `_owned_resume`: the
response should not confirm that an id exists.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CandidateDep, QueueDep, RetrieverDep, SessionDep, SettingsDep
from app.config import Settings
from app.jobs import is_stalled
from app.models import Candidate, Job, Resume, Screening, ScreeningStatus
from app.pipeline.judge import requirements_fingerprint
from app.pipeline.prompts import JUDGMENT_PROMPT_VERSION
from app.pipeline.ranking import rank_screenings
from app.pipeline.retrieval import RetrievableDocument
from app.schemas.ranking import Ranking
from app.services import screening_service

router = APIRouter(tags=["screenings"])

RETRYABLE_STATUSES = frozenset({ScreeningStatus.DEAD_LETTERED, ScreeningStatus.FAILED})
"""`completed` is absent because re-running a current result would bill a call to
reproduce it — ask again through `POST /jobs/{id}/screenings`, which re-queues
exactly when the answer is out of date. `pending` and `processing` are absent
because the work is already on its way."""


def can_retry(screening: Screening, settings: Settings) -> bool:
    """The screening twin of `resumes.can_retry`, and for the same reason.

    A screening held at `processing` past the visibility timeout is not on its way
    anywhere: the worker that claimed it is gone. `jobs.reclaim_stalled` sweeps it
    where a worker runs, and this is the door to open by hand where none does.
    """
    if screening.status in RETRYABLE_STATUSES:
        return True
    return screening.status is ScreeningStatus.PROCESSING and is_stalled(
        screening.last_attempt_at, timeout_seconds=settings.job_visibility_timeout_seconds
    )


class ScreeningIn(BaseModel):
    resume_id: uuid.UUID


class ScreeningOut(BaseModel):
    id: str
    job_id: str
    resume_id: str
    status: ScreeningStatus
    failure_reason: str | None
    attempts: int
    can_retry: bool

    requirements_met: int
    requirements_total: int
    claims_verified: int
    claims_dropped: int
    hallucination_rate: float

    is_stale: bool
    """The requirements or the judging prompt changed after this ran, so the result
    answers a question nobody is asking any more. Reported rather than hidden or
    silently recomputed: it was true of what it saw, and re-running costs money."""

    @classmethod
    def of(
        cls, screening: Screening, *, requirements_hash: str, settings: Settings
    ) -> ScreeningOut:
        return cls(
            id=str(screening.id),
            job_id=str(screening.job_id),
            resume_id=str(screening.resume_id),
            status=screening.status,
            failure_reason=screening.failure_reason,
            attempts=screening.attempts,
            # Takes settings because the answer is time-dependent: a stalled
            # `processing` screening becomes retryable, and the timeout says when.
            can_retry=can_retry(screening, settings),
            requirements_met=screening.requirements_met,
            requirements_total=screening.requirements_total,
            claims_verified=screening.claims_verified,
            claims_dropped=screening.claims_dropped,
            hallucination_rate=screening.hallucination_rate,
            is_stale=screening.is_stale(
                requirements_hash=requirements_hash, prompt_version=JUDGMENT_PROMPT_VERSION
            ),
        )


class CandidateSuggestion(BaseModel):
    """One resume's place in the "who is worth judging first" order."""

    resume_id: str
    filename: str

    score: float
    """Relative to the other entries in this response and meaningless on its own.
    Deliberately **not** comparable with a `RankedEntry.score`, which is a weighted
    share of requirements *proved* rather than a guess at relevance."""

    matched: list[str]
    """Which of the job's requirement labels were found in the document. Carried
    because a bare relevance number is the kind of figure this project refuses to
    produce — and because it is what makes a surprising order checkable."""

    already_screened: bool
    """So a client can offer the unscreened ones first without a second request.
    Not a filter: a screened resume still appears, in its place."""


class ScreeningDetail(BaseModel):
    screening: ScreeningOut
    judgment: dict[str, Any] | None
    """The full `Judgment`: per-requirement verdicts with their citations, plus the
    dropped claims. Behind the single-screening route rather than the list, which a
    UI renders many of at once."""

    document_text: str | None
    """The exact text every citation offset indexes into, so the UI can highlight
    spans without re-parsing and risking a shifted offset — same contract as
    `GET /resumes/{id}`."""


async def _owned_job(session: SessionDep, *, job_id: uuid.UUID, candidate: Candidate) -> Job:
    job = (
        await session.execute(
            select(Job).where(Job.id == job_id).options(selectinload(Job.requirements))
        )
    ).scalar_one_or_none()
    if job is None or job.owner_id != candidate.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


async def _owned_screening(
    session: SessionDep, *, screening_id: uuid.UUID, candidate: Candidate
) -> tuple[Screening, Job]:
    """A screening whose *job* the caller owns, plus that job with requirements.

    The job comes back loaded because every response needs the current fingerprint
    to answer `is_stale`, and a lazy load after the fact is an error on an async
    session rather than a query.
    """
    screening = (
        await session.execute(select(Screening).where(Screening.id == screening_id))
    ).scalar_one_or_none()
    if screening is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Screening not found")

    job = (
        await session.execute(
            select(Job).where(Job.id == screening.job_id).options(selectinload(Job.requirements))
        )
    ).scalar_one_or_none()
    if job is None or job.owner_id != candidate.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Screening not found")
    return screening, job


def _fingerprint(job: Job) -> str:
    return requirements_fingerprint(screening_service.requirement_specs(job))


def _retrieval_terms(job: Job) -> list[str]:
    """What a job is matched on: its requirement labels, and their details.

    Deliberately not `job.description`. The description is stored for context and
    audit and is explicitly not what anyone is judged against (docs/HANDOFF.md §5);
    letting it steer retrieval would quietly reintroduce free-text matching through
    the back door, on the one input nobody decomposed on purpose.
    """
    terms: list[str] = []
    for requirement in sorted(job.requirements, key=lambda item: item.position):
        terms.append(requirement.label)
        if requirement.detail:
            terms.append(requirement.detail)
    return terms


@router.post("/jobs/{job_id}/screenings", response_model=ScreeningOut)
async def create_screening(
    job_id: uuid.UUID,
    payload: ScreeningIn,
    candidate: CandidateDep,
    session: SessionDep,
    queue: QueueDep,
    settings: SettingsDep,
    response: Response,
) -> ScreeningOut:
    """Screen one of the caller's resumes against one of their jobs.

    Idempotent in the way uploading is: asking twice for a screening that is already
    current returns it without spending a second model call. It *is* re-queued when
    the requirements or the prompt have changed since it ran, or when the last
    attempt failed — `screening_service.request_screening` owns that rule.

    Answers `202 Accepted` when work was queued and `200 OK` when the existing
    result already answers the question.
    """
    job = await _owned_job(session, job_id=job_id, candidate=candidate)

    resume = (
        await session.execute(select(Resume).where(Resume.id == payload.resume_id))
    ).scalar_one_or_none()
    if resume is None or resume.candidate_id != candidate.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")

    screening, queued = await screening_service.request_screening(
        session, job=job, resume=resume, queue=queue
    )

    response.status_code = status.HTTP_202_ACCEPTED if queued else status.HTTP_200_OK
    return ScreeningOut.of(screening, requirements_hash=_fingerprint(job), settings=settings)


@router.get("/jobs/{job_id}/screenings", response_model=list[ScreeningOut])
async def list_screenings(
    job_id: uuid.UUID, candidate: CandidateDep, session: SessionDep, settings: SettingsDep
) -> list[ScreeningOut]:
    """Every screening for one job, newest first.

    Deliberately *not* the ranked view: this is the raw list, including the ones
    still running and the ones that failed. `GET /jobs/{job_id}/ranking` is the
    ordered answer.
    """
    job = await _owned_job(session, job_id=job_id, candidate=candidate)
    fingerprint = _fingerprint(job)

    result = await session.execute(
        select(Screening).where(Screening.job_id == job.id).order_by(Screening.created_at.desc())
    )
    return [
        ScreeningOut.of(screening, requirements_hash=fingerprint, settings=settings)
        for screening in result.scalars()
    ]


@router.get("/jobs/{job_id}/ranking", response_model=Ranking)
async def get_ranking(job_id: uuid.UUID, candidate: CandidateDep, session: SessionDep) -> Ranking:
    """Order this job's candidates by what their citations prove.

    Computed on read and costs nothing: no model call, no stored ranking, no
    migration. That is what lets a recruiter adjust a weight and see the list
    reorder immediately while every screening stays current — `must_have` and
    `weight` are excluded from the requirements fingerprint precisely so that
    editing one cannot re-bill a screening (`pipeline/judge.requirements_fingerprint`).

    Screenings that cannot take part come back in `excluded` with the reason,
    rather than being hidden or silently re-run.
    """
    job = await _owned_job(session, job_id=job_id, candidate=candidate)
    requirements = screening_service.requirement_specs(job)

    result = await session.execute(select(Screening).where(Screening.job_id == job.id))

    return rank_screenings(
        [screening_service.screening_view(screening) for screening in result.scalars()],
        requirements,
        requirements_hash=requirements_fingerprint(requirements),
        prompt_version=JUDGMENT_PROMPT_VERSION,
    )


@router.get("/jobs/{job_id}/candidates", response_model=list[CandidateSuggestion])
async def suggest_candidates(
    job_id: uuid.UUID,
    candidate: CandidateDep,
    session: SessionDep,
    retriever: RetrieverDep,
) -> list[CandidateSuggestion]:
    """Order the caller's resumes by how worth screening they look.

    A screening costs one model call per resume, so this exists to say where to
    spend it first. It spends nothing itself: term overlap over `document_text` the
    database already holds, with no model call and no index.

    **Every screenable resume comes back, ordered — nothing is filtered out.** A
    retriever that dropped its tail would remove a person from consideration with no
    way to see that it happened, which is the failure `excluded` exists to prevent
    one layer down. The cut-off is the caller's, made in the open.

    The score answers "does this document look worth reading", which is *not* the
    question `GET /jobs/{job_id}/ranking` answers. Retrieval never sees a verdict and
    never affects one.
    """
    job = await _owned_job(session, job_id=job_id, candidate=candidate)

    result = await session.execute(
        select(Resume).where(
            Resume.candidate_id == candidate.id,
            # A resume with no stored text cannot be screened — `run_screening_job`
            # raises `NotScreenable` — so offering it here would only promise work
            # that must fail.
            Resume.document_text.is_not(None),
        )
    )
    resumes = list(result.scalars())

    documents = [
        RetrievableDocument(resume_id=str(resume.id), text=resume.document_text or "")
        for resume in resumes
    ]
    hits = retriever.retrieve(_retrieval_terms(job), documents)

    by_id = {str(resume.id): resume for resume in resumes}
    screened = {
        str(row.resume_id)
        for row in (
            await session.execute(select(Screening).where(Screening.job_id == job.id))
        ).scalars()
    }

    return [
        CandidateSuggestion(
            resume_id=hit.resume_id,
            filename=by_id[hit.resume_id].filename,
            score=round(hit.score, 4),
            matched=hit.matched,
            already_screened=hit.resume_id in screened,
        )
        for hit in hits
    ]


@router.post("/screenings/{screening_id}/retry", response_model=ScreeningOut)
async def retry_screening(
    screening_id: uuid.UUID,
    candidate: CandidateDep,
    session: SessionDep,
    queue: QueueDep,
    settings: SettingsDep,
) -> ScreeningOut:
    """Replay a screening that gave up, or one a dead worker is still holding.

    The dead-letter half, as for resumes — and, past the visibility timeout, the
    stalled-`processing` half too.
    """
    screening, job = await _owned_screening(session, screening_id=screening_id, candidate=candidate)

    if not can_retry(screening, settings):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A screening with status '{screening.status}' cannot be retried. "
                "It is either already in progress or already finished."
            ),
        )

    resume = await session.get(Resume, screening.resume_id)
    if resume is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Screening not found")

    # `force` because a dead letter and a permanent failure both leave a row that
    # `request_screening` would otherwise judge current enough to leave alone.
    await screening_service.request_screening(
        session, job=job, resume=resume, queue=queue, force=True
    )
    return ScreeningOut.of(screening, requirements_hash=_fingerprint(job), settings=settings)


@router.get("/screenings/{screening_id}", response_model=ScreeningDetail)
async def get_screening(
    screening_id: uuid.UUID, candidate: CandidateDep, session: SessionDep, settings: SettingsDep
) -> ScreeningDetail:
    screening, job = await _owned_screening(session, screening_id=screening_id, candidate=candidate)
    resume = await session.get(Resume, screening.resume_id)

    return ScreeningDetail(
        screening=ScreeningOut.of(
            screening, requirements_hash=_fingerprint(job), settings=settings
        ),
        judgment=screening.result,
        document_text=resume.document_text if resume else None,
    )
