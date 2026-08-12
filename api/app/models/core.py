"""Tables for M1: a candidate, their uploaded resumes, and what we learned.

Two deliberate shape choices:

*   The verified profile is stored as one JSON document rather than normalized into
    claim/evidence tables. Its shape is still moving, and M3 introduces
    requirement-level tables anyway — normalizing twice would be wasted work.
*   The verification counters are lifted out of that JSON into real columns. Cost
    and hallucination dashboards should be plain SQL, not JSON path digging.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import JSON_VARIANT, Base, Timestamps, UUIDPrimaryKey


class ResumeStatus(StrEnum):
    PENDING = "pending"
    """Queued. Also where a resume waits between retries."""

    PROCESSING = "processing"
    """A worker has claimed it. A resume stuck here means a worker died mid-job."""

    PARSED = "parsed"
    """Text extracted; extraction not run or not finished.

    Set while a job is running, but no longer committed as a resting state — every
    path out of the job overwrites it. Rows written before the retry policy landed
    can still hold it, which is why it is accepted for retry."""

    EXTRACTED = "extracted"
    """A verified profile exists."""

    FAILED = "failed"
    """This document cannot be processed — see `failure_reason`. Permanent, so
    retrying it would only fail the same way."""

    DEAD_LETTERED = "dead_lettered"
    """Retries were exhausted on failures that looked transient. Distinct from
    `failed` because this one is worth retrying — see `POST /resumes/{id}/retry`."""


class Role(StrEnum):
    """What an account is allowed to do (M4 slice 2).

    Deliberately a column on the one actor this system has rather than a second
    table: M3's handoff promised RBAC would widen *who* may own a job without
    changing the shape of anything, and this keeps that promise. Ownership checks
    are unchanged — a role says which routes you may reach, never which rows.
    """

    CANDIDATE = "candidate"
    """Uploads resumes and applies. The default for a new account."""

    RECRUITER = "recruiter"
    """Also posts jobs and screens the people who applied to them."""

    ADMIN = "admin"
    """Everything. Deliberately not self-selectable at registration — it is set out
    of band, because an account that can grant itself admin is not a role system."""


class Candidate(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "candidates"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    password_hash: Mapped[str | None] = mapped_column(String(200))

    role: Mapped[Role] = mapped_column(
        Enum(Role, native_enum=False, length=20), default=Role.CANDIDATE, nullable=False
    )

    resumes: Mapped[list[Resume]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan"
    )


class Resume(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "resumes"
    __table_args__ = (
        # Re-uploading the same bytes should resolve to the existing row rather
        # than paying to extract it twice.
        UniqueConstraint("candidate_id", "content_hash", name="uq_resumes_candidate_content"),
        Index("ix_resumes_status", "status"),
    )

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    """SHA-256 of the uploaded bytes. Drives dedupe and idempotent re-upload."""

    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    """Opaque to the app: a filesystem path in M1, an object key once MinIO lands."""

    status: Mapped[ResumeStatus] = mapped_column(
        Enum(ResumeStatus, native_enum=False, length=20),
        default=ResumeStatus.PENDING,
        nullable=False,
    )
    failure_reason: Mapped[str | None] = mapped_column(Text)

    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """Total times a worker has claimed this resume. Never reset — it is what
    makes each dispatch's queue job id unique, so a manual retry is not mistaken
    for a job that is already queued."""

    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """Consecutive failures. This is the retry budget, so a success or a manual
    retry clears it; `attempts` deliberately does not."""

    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    page_count: Mapped[int | None] = mapped_column(Integer)
    pages_without_text: Mapped[list[int] | None] = mapped_column(JSON_VARIANT)
    """Pages that yielded no usable text even after OCR — nothing on them is citable."""

    pages_from_ocr: Mapped[list[int] | None] = mapped_column(JSON_VARIANT)
    """Pages whose text was recognized from an image rather than read from a text
    layer. Kept because a citation into one of these is faithful to what was read,
    not necessarily to what was printed, and the user is told so."""

    document_text: Mapped[str | None] = mapped_column(Text)
    """The parsed text. Evidence offsets index into exactly this string, so it has
    to be stored verbatim — re-parsing later could shift every offset."""

    page_spans: Mapped[list[dict[str, int]] | None] = mapped_column(JSON_VARIANT)
    """Where each page begins and ends inside `document_text`.

    Stored because a quote located in that text *later* — which is what judging a
    requirement does — has no other way to name a page. Extraction never needed
    this: it reads the live `ParsedDocument` it just built. Holds `PageSpan`'s own
    field names, so `ParsedDocument.from_stored` reads it back with no mapping
    layer. Null on rows written before migration `0005`; those report page 1."""

    candidate: Mapped[Candidate] = relationship(back_populates="resumes")
    profile: Mapped[ExtractedProfileRow | None] = relationship(
        back_populates="resume", cascade="all, delete-orphan", uselist=False
    )
    llm_calls: Mapped[list[LLMCallLog]] = relationship(
        back_populates="resume", cascade="all, delete-orphan"
    )


class ExtractedProfileRow(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "extracted_profiles"

    resume_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    profile: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT, nullable=False)
    """A serialized `ExtractedProfile`, including its dropped claims."""

    # Lifted out of the JSON so the metrics query is a GROUP BY, not a JSON walk.
    claims_verified: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    claims_dropped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hallucination_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    resume: Mapped[Resume] = relationship(back_populates="profile")


class LLMCallLog(UUIDPrimaryKey, Timestamps, Base):
    """One row per model call.

    Recorded unconditionally, including for the fake backend, so "cost per
    application" and "cache hit rate" are measured rather than estimated.
    """

    __tablename__ = "llm_call_logs"
    __table_args__ = (Index("ix_llm_call_logs_provider_model", "provider", "model"),)

    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), index=True
    )

    screening_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("screenings.id", ondelete="CASCADE"), index=True
    )
    """Set instead of `resume_id` for a judging call. Both are nullable and exactly
    one is filled: a call belongs to the piece of work that paid for it, and a
    screening is not a resume. Without this a judging call would either hang off the
    resume — making "what did extracting this document cost" wrong — or go
    unrecorded, and an unrecorded call is a cost figure that quietly lies."""

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(60), nullable=False)
    """Which prompt produced this row — otherwise comparing prompt revisions is guesswork."""

    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    """Null when the provider's price is unknown — never a misleading zero."""

    resume: Mapped[Resume | None] = relationship(back_populates="llm_calls")
