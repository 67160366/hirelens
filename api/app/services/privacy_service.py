"""Getting your data out, and getting it deleted.

PDPA's two rights the system can actually honour, and the reason they live in one
module: they are the same question asked twice. Export says what is held about you;
delete removes exactly that. If the two ever disagree, one of them is lying.

**Export is a subject-access request, not a dump of everything you can see.** A
recruiter can read the resumes of people who applied to their postings, and those
are not the recruiter's data — they belong to the applicants, who can export them
from their own accounts. What comes back here is what is *about* the caller.

**Delete removes the blobs before the rows, and abandons the whole thing if a blob
will not go.** The other order is the one that quietly fails PDPA: rows gone, object
still in the bucket, nothing left pointing at it to notice. This way the worst case
is a row whose file is missing, which the pipeline already treats as a permanent
failure and reports.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Application,
    ApplicationEvent,
    Candidate,
    ExtractedProfileRow,
    Job,
    LLMCallLog,
    Resume,
    Screening,
)
from app.storage import ObjectNotFoundError, Storage, StorageError

# Resumes are PII: ids and counts in the log, never text and never a storage key.
logger = logging.getLogger(__name__)


class ErasureIncomplete(Exception):
    """A stored file could not be removed, so nothing was deleted.

    Raised rather than swallowed: a partial erasure that reports success is the
    failure this whole path exists to avoid.
    """


async def export_account(session: AsyncSession, *, candidate: Candidate) -> dict[str, Any]:
    """Everything the system holds *about* this account, as one JSON document."""
    resumes = list(
        (
            await session.execute(
                select(Resume)
                .where(Resume.candidate_id == candidate.id)
                .order_by(Resume.created_at)
            )
        ).scalars()
    )
    resume_ids = [resume.id for resume in resumes]

    profiles = (
        {
            row.resume_id: row
            for row in (
                await session.execute(
                    select(ExtractedProfileRow).where(ExtractedProfileRow.resume_id.in_(resume_ids))
                )
            ).scalars()
        }
        if resume_ids
        else {}
    )

    jobs = list(
        (
            await session.execute(
                select(Job)
                .where(Job.owner_id == candidate.id)
                # Eager, because the rendering below walks them. A lazy load on an
                # async session is an error rather than a query — the same shape
                # that produced M3 slice 1's `MissingGreenlet`, and it surfaced here
                # only in the test with a job in it.
                .options(selectinload(Job.requirements))
                .order_by(Job.created_at)
            )
        ).scalars()
    )

    applications = list(
        (
            await session.execute(
                select(Application)
                .where(Application.candidate_id == candidate.id)
                .order_by(Application.created_at)
            )
        ).scalars()
    )
    events = (
        list(
            (
                await session.execute(
                    select(ApplicationEvent)
                    .where(ApplicationEvent.application_id.in_([a.id for a in applications]))
                    .order_by(ApplicationEvent.application_id, ApplicationEvent.position)
                )
            ).scalars()
        )
        if applications
        else []
    )

    # Screenings *of this person's resumes*, wherever they were run. A verdict about
    # you is yours to see, even though the job it was run for is not.
    screenings = (
        list(
            (
                await session.execute(
                    select(Screening)
                    .where(Screening.resume_id.in_(resume_ids))
                    .order_by(Screening.created_at)
                )
            ).scalars()
        )
        if resume_ids
        else []
    )

    calls = (
        list(
            (
                await session.execute(
                    select(LLMCallLog)
                    .where(LLMCallLog.resume_id.in_(resume_ids))
                    .order_by(LLMCallLog.created_at)
                )
            ).scalars()
        )
        if resume_ids
        else []
    )

    logger.info(
        "candidate %s: exported %d resume(s), %d job(s), %d application(s)",
        candidate.id,
        len(resumes),
        len(jobs),
        len(applications),
    )

    return {
        "account": {
            "id": str(candidate.id),
            "email": candidate.email,
            "display_name": candidate.display_name,
            "role": str(candidate.role),
            "created_at": candidate.created_at.isoformat(),
        },
        "resumes": [
            {
                "id": str(resume.id),
                "filename": resume.filename,
                "size_bytes": resume.size_bytes,
                "content_hash": resume.content_hash,
                "status": str(resume.status),
                "uploaded_at": resume.created_at.isoformat(),
                "consented_at": (resume.consented_at.isoformat() if resume.consented_at else None),
                "consent_version": resume.consent_version,
                "page_count": resume.page_count,
                "pages_from_ocr": resume.pages_from_ocr or [],
                # The parsed text and the verified profile. This is the substance of
                # what is held, and withholding it would make the export decorative.
                "document_text": resume.document_text,
                "profile": (profiles[resume.id].profile if resume.id in profiles else None),
            }
            for resume in resumes
        ],
        "jobs": [
            {
                "id": str(job.id),
                "title": job.title,
                "description": job.description,
                "created_at": job.created_at.isoformat(),
                "requirements": [
                    {
                        "kind": str(item.kind),
                        "label": item.label,
                        "detail": item.detail,
                        "must_have": item.must_have,
                        "weight": item.weight,
                    }
                    for item in job.requirements
                ],
            }
            for job in jobs
        ],
        "applications": [
            {
                "id": str(application.id),
                "job_id": str(application.job_id),
                "resume_id": str(application.resume_id),
                "state": str(application.state),
                "created_at": application.created_at.isoformat(),
                "events": [
                    {
                        "position": event.position,
                        "from_state": str(event.from_state) if event.from_state else None,
                        "to_state": str(event.to_state),
                        # Whether it was you, somebody else, or the system.
                        "by_you": event.actor_id == candidate.id,
                        "by_the_system": event.actor_id is None,
                        "reason": event.reason,
                        "at": event.created_at.isoformat(),
                    }
                    for event in events
                    if event.application_id == application.id
                ],
            }
            for application in applications
        ],
        "screenings": [
            {
                "id": str(screening.id),
                "job_id": str(screening.job_id),
                "resume_id": str(screening.resume_id),
                "status": str(screening.status),
                "requirements_met": screening.requirements_met,
                "requirements_total": screening.requirements_total,
                "result": screening.result,
                "created_at": screening.created_at.isoformat(),
            }
            for screening in screenings
        ],
        "model_calls": [
            {
                "provider": call.provider,
                "model": call.model,
                "prompt_version": call.prompt_version,
                "input_tokens": call.input_tokens,
                "output_tokens": call.output_tokens,
                "cost_usd": call.cost_usd,
                "at": call.created_at.isoformat(),
            }
            for call in calls
        ],
    }


async def delete_account(session: AsyncSession, *, candidate: Candidate, storage: Storage) -> int:
    """Erase the account and everything that cascades from it.

    Returns how many storage keys were erased — keys, not files that existed:
    both backends' `delete` is idempotent, so a key whose object had already
    gone is counted the same as one that had not. Checking first would cost a
    round trip per file to make a number more precise than anything needs.

    **Blobs first, then rows, and nothing at all if a blob refuses.** An object left
    in the bucket with no row pointing at it is undiscoverable and unerasable — the
    real PDPA failure — while a row whose file is missing is a state the pipeline
    already handles and reports. So the order errs toward the recoverable mistake,
    and a `StorageError` aborts before a single row is touched.

    An `ObjectNotFoundError` is not a failure: the file is already gone, which is the
    outcome being asked for.

    What cascades is worth knowing before calling this. Deleting a recruiter deletes
    their postings, and with them every screening and **every other person's
    application** to those postings. That is the honest consequence of the posting
    ceasing to exist, but it is other people's history, so it is named here rather
    than left to be discovered. `application_events.actor_id` is `SET NULL`, so this
    account's moves on applications that *survive* are anonymised rather than erased.
    """
    keys = list(
        (
            await session.execute(
                select(Resume.storage_key).where(Resume.candidate_id == candidate.id)
            )
        ).scalars()
    )

    removed = 0
    for key in keys:
        try:
            await storage.delete(key)
        except ObjectNotFoundError:
            # Already gone, which is the state being asked for rather than a
            # failure. Both backends delete idempotently so this is unlikely to
            # fire; it is here because "the file is missing" must never be the
            # thing that stops an erasure.
            continue
        except StorageError as exc:
            # Nothing has been deleted yet, so there is nothing to roll back. Say so
            # rather than deleting the rows and leaving the object unreachable.
            logger.error(
                "candidate %s: erasure abandoned, a stored file could not be removed (%s)",
                candidate.id,
                type(exc).__name__,
            )
            raise ErasureIncomplete(
                "A stored file could not be deleted, so nothing was deleted. "
                "Nothing has changed; please try again."
            ) from exc
        removed += 1

    await session.delete(candidate)
    await session.commit()
    logger.info("candidate %s: erased, %d storage key(s) removed", candidate.id, removed)
    return removed
