"""The public careers site's read side: postings a stranger may see.

**The first routes in this system that take no account at all.** Everything else
resolves a `Candidate` first, which was right while every screen belonged to
somebody. A careers board belongs to nobody: a person deciding whether to apply
has not registered yet, and asking them to before they can read the advertisement
is the shape this project set out to argue with.

Read-only, and that is a boundary rather than a phase. Applying, uploading and
every state change stay behind `CandidateDep` — a stranger may read what the
company published and nothing else.

**`PostingOut` is narrower than `JobOut`, and the difference is the point.**
`JobOut` is what the authoring surface returns to the person who wrote the
posting; this is what the posting *is* to everyone else:

- **No `owner_id`.** It is an account id, and it names which employee typed the
  advertisement — a fact about the company's staff, published to the internet, for
  no reader's benefit.
- **No `weight`.** It is ranking's tuning, it never reached the judge, and
  publishing it is publishing instructions for gaming the screening. `must_have`
  stays: what you will be measured on is not a secret, and hiding it while
  screening on it is the ATS behaviour this project exists to refuse.
- **No `status`.** Everything reachable here is published by construction. A field
  whose value is always the same invites a client to branch on it, and a client
  branching on a security property is a client that can get it wrong.
- **No requirement `id` or `position`.** The list arrives in order; ids here would
  be an invitation to join a public list against a private one.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import publication
from app.api.deps import SessionDep
from app.models import Job, JobRequirement, JobStatus, RequirementKind

router = APIRouter(prefix="/careers", tags=["careers"])


class PostingRequirementOut(BaseModel):
    """One thing this posting asks for, as an applicant is shown it."""

    kind: RequirementKind
    label: str
    detail: str | None
    must_have: bool

    @classmethod
    def of(cls, requirement: JobRequirement) -> PostingRequirementOut:
        return cls(
            kind=requirement.kind,
            label=requirement.label,
            detail=requirement.detail,
            must_have=requirement.must_have,
        )


class PostingOut(BaseModel):
    id: str
    title: str
    description: str | None
    location: str | None
    published_at: datetime | None
    requirements: list[PostingRequirementOut]

    @classmethod
    def of(cls, job: Job) -> PostingOut:
        return cls(
            id=str(job.id),
            title=job.title,
            description=job.description,
            location=job.location,
            published_at=job.published_at,
            requirements=[PostingRequirementOut.of(item) for item in job.requirements],
        )


@router.get("/postings", response_model=list[PostingOut])
async def list_postings(session: SessionDep) -> list[PostingOut]:
    """Every published posting, newest first.

    Ordered by `published_at`, never by `updated_at`: editing a live posting must
    not send it back to the top of the board, which is the whole reason migration
    `0013` stored a separate column for it.

    No NULL-ordering question arises, and that is by construction rather than by
    luck — `0013` backfilled `published_at` from `created_at` and the publish route
    sets it, so a `PUBLISHED` row without one does not exist. Worth saying because
    SQLite and Postgres sort NULLs to opposite ends under `DESC`, and this suite
    runs on the one the deployment does not.
    """
    result = await session.execute(
        select(Job)
        .where(Job.status == JobStatus.PUBLISHED)
        .options(selectinload(Job.requirements))
        .order_by(Job.published_at.desc(), Job.created_at.desc())
    )
    return [PostingOut.of(job) for job in result.scalars()]


@router.get("/postings/{posting_id}", response_model=PostingOut)
async def get_posting(posting_id: uuid.UUID, session: SessionDep) -> PostingOut:
    """One published posting, or 404.

    The predicate is `publication.is_public`, which `_readable_job` also uses, so
    the public page and a signed-in candidate's read cannot answer the question
    differently — three copies of a security predicate is three chances to get it
    wrong once.

    A draft and a posting that never existed are the same 404 with the same body.
    Anything else would make this route a way to count how many jobs the company
    has in progress.
    """
    job = (
        await session.execute(
            select(Job).where(Job.id == posting_id).options(selectinload(Job.requirements))
        )
    ).scalar_one_or_none()

    if job is None or not publication.is_public(job.status):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Posting not found")
    return PostingOut.of(job)
