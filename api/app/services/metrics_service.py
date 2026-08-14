"""The queries behind the usage and quality dashboard (M5 slice 2).

**No model call, no new table, no migration.** Every figure is a `GROUP BY` over rows
the system already wrote while doing its work, which is the whole organizing idea of
this milestone — see `app/schemas/metrics.py` for it stated properly.

Two things here are load-bearing and easy to undo by accident:

**One query, folded up in Python.** Totals, per-bucket subtotals and per-group rows all
come from a single `GROUP BY (provider, model, prompt_version, bucket)`. Issuing a
separate `SELECT SUM(...)` for the headline total is the obvious implementation and it
lets the headline disagree with the breakdown under it — most easily when the scoping
predicate is edited in one place and not the other. Deriving them means they cannot
drift, and `test_metrics.py` asserts the partition is exact.

**Owner scoping is two arms and three joins**, because `llm_call_logs` has no owner
column at all: an extraction call reaches its owner through `resumes.candidate_id`, and
a judging call through `screenings -> jobs.owner_id`. There is no single join that
covers both, and writing one would silently drop whichever half it missed.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models import (
    Candidate,
    ExtractedProfileRow,
    Job,
    LLMCallLog,
    Resume,
    ResumeStatus,
    Role,
    Screening,
)
from app.schemas.metrics import (
    CallBucket,
    CallGroup,
    CallTotals,
    ParseOutcome,
    QualitySummary,
    UsageReport,
    UsageScope,
)


def scope_for(candidate: Candidate) -> UsageScope:
    """Whose rows this account may total.

    Read from the row rather than gated on the route: `require_role` refuses a route
    and returns the caller unchanged, so it cannot widen a query — using it for "admin
    sees everything" would 403 exactly the accounts that own the extraction rows. This
    is `_owned_resume`'s pattern, one grain coarser.
    """
    return UsageScope.ALL if candidate.role is Role.ADMIN else UsageScope.OWN


def _owned_call_predicate(candidate: Candidate) -> ColumnElement[bool]:
    """The two arms, as one predicate over `llm_call_logs`.

    An unattributed row (both ids null) matches neither arm and so never reaches a
    scoped caller — correctly, since nobody owns it. It is still counted for `ADMIN`,
    which is the point of bucketing it rather than filtering it away.
    """
    own_resumes = select(Resume.id).where(Resume.candidate_id == candidate.id)
    own_screenings = (
        select(Screening.id)
        .join(Job, Job.id == Screening.job_id)
        .where(Job.owner_id == candidate.id)
    )
    return or_(
        LLMCallLog.resume_id.in_(own_resumes),
        LLMCallLog.screening_id.in_(own_screenings),
    )


_BUCKET = case(
    (
        LLMCallLog.resume_id.is_not(None) & LLMCallLog.screening_id.is_(None),
        CallBucket.EXTRACTION.value,
    ),
    (
        LLMCallLog.screening_id.is_not(None) & LLMCallLog.resume_id.is_(None),
        CallBucket.JUDGING.value,
    ),
    (
        LLMCallLog.resume_id.is_(None) & LLMCallLog.screening_id.is_(None),
        CallBucket.UNATTRIBUTED.value,
    ),
    else_=CallBucket.AMBIGUOUS.value,
)
"""Which piece of work paid for a call, decided in SQL so the four cases are exhaustive
by construction. The `else_` is the both-set case: an unenforced xor means it is legal,
and it must be told apart from the row that is merely missing."""


def _empty_totals() -> CallTotals:
    """The identity to fold groups into.

    `cost_usd` starts at **0.0, not `None`** — it is the additive identity, and seeding
    it with "unknown" would make `_add_optional` swallow every real cost that followed,
    since unknown is contagious by design. Nothing was spent on no calls, which is a
    true statement; the latency *mean* starts at `None` instead, because the mean of
    zero samples is not zero, it does not exist.
    """
    return CallTotals(
        calls=0,
        input_tokens=0,
        output_tokens=0,
        cached_input_tokens=0,
        latency_ms_total=0,
        latency_ms_mean=None,
        calls_priced=0,
        cost_usd=0.0,
    )


def _accumulate(into: CallTotals, row: CallTotals) -> CallTotals:
    """Fold one group into a running subtotal.

    Cost is deliberately not summed here — it is recomputed at the end from the summed
    `cost_usd` of only the *priced* calls, and then discarded unless every call in the
    subtotal was priced. Adding `None` into a running float is where a partial total
    would sneak back in.
    """
    return CallTotals(
        calls=into.calls + row.calls,
        input_tokens=into.input_tokens + row.input_tokens,
        output_tokens=into.output_tokens + row.output_tokens,
        cached_input_tokens=into.cached_input_tokens + row.cached_input_tokens,
        latency_ms_total=into.latency_ms_total + row.latency_ms_total,
        latency_ms_mean=None,
        calls_priced=into.calls_priced + row.calls_priced,
        cost_usd=_add_optional(into.cost_usd, row.cost_usd),
    )


def _add_optional(left: float | None, right: float | None) -> float | None:
    """Sum two partial costs, keeping "unknown" contagious.

    `None + anything` is unknown, because a subtotal containing one unpriced call
    cannot honestly be reported as a number.
    """
    if left is None or right is None:
        return None
    return left + right


def _finish(totals: CallTotals) -> CallTotals:
    """Fill in the derived fields once a subtotal is complete."""
    mean = totals.latency_ms_total / totals.calls if totals.calls else None
    cost = totals.cost_usd if totals.calls_priced == totals.calls else None
    return totals.model_copy(update={"latency_ms_mean": mean, "cost_usd": cost})


def _scoped(
    query: Select[tuple[object, ...]], *, predicate: ColumnElement[bool] | None
) -> Select[tuple[object, ...]]:
    return query if predicate is None else query.where(predicate)


async def build_usage_report(session: AsyncSession, *, candidate: Candidate) -> UsageReport:
    """Everything the dashboard renders, from rows that already exist."""
    scope = scope_for(candidate)
    call_predicate = None if scope is UsageScope.ALL else _owned_call_predicate(candidate)

    groups = await _call_groups(session, predicate=call_predicate)

    by_bucket: dict[CallBucket, CallTotals] = {bucket: _empty_totals() for bucket in CallBucket}
    running_total = _empty_totals()
    for group in groups:
        by_bucket[group.bucket] = _accumulate(by_bucket[group.bucket], group.totals)
        running_total = _accumulate(running_total, group.totals)

    return UsageReport(
        scope=scope,
        generated_at=datetime.now(UTC),
        totals=_finish(running_total),
        by_bucket={bucket: _finish(totals) for bucket, totals in by_bucket.items()},
        by_group=groups,
        quality=await _quality(session, candidate=candidate, scope=scope),
        parse_outcomes=await _parse_outcomes(session, candidate=candidate, scope=scope),
    )


async def _call_groups(
    session: AsyncSession, *, predicate: ColumnElement[bool] | None
) -> list[CallGroup]:
    """Model calls, grouped by who served them, which prompt asked, and who paid."""
    query = select(
        LLMCallLog.provider,
        LLMCallLog.model,
        LLMCallLog.prompt_version,
        _BUCKET.label("bucket"),
        func.count().label("calls"),
        func.coalesce(func.sum(LLMCallLog.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(LLMCallLog.output_tokens), 0).label("output_tokens"),
        func.coalesce(func.sum(LLMCallLog.cached_input_tokens), 0).label("cached_input_tokens"),
        func.coalesce(func.sum(LLMCallLog.latency_ms), 0).label("latency_ms_total"),
        # count() over a nullable column counts the non-nulls, which is exactly
        # "how many of these calls have a known price".
        func.count(LLMCallLog.cost_usd).label("calls_priced"),
        func.sum(LLMCallLog.cost_usd).label("cost_usd"),
    ).group_by(
        LLMCallLog.provider,
        LLMCallLog.model,
        LLMCallLog.prompt_version,
        _BUCKET,
    )

    rows = (await session.execute(_scoped(query, predicate=predicate))).all()

    groups = [
        CallGroup(
            provider=row.provider,
            model=row.model,
            prompt_version=row.prompt_version,
            bucket=CallBucket(row.bucket),
            totals=_finish(
                CallTotals(
                    calls=row.calls,
                    input_tokens=row.input_tokens,
                    output_tokens=row.output_tokens,
                    cached_input_tokens=row.cached_input_tokens,
                    latency_ms_total=row.latency_ms_total,
                    latency_ms_mean=None,
                    calls_priced=row.calls_priced,
                    cost_usd=row.cost_usd,
                )
            ),
        )
        for row in rows
    ]
    # Ordered here rather than in SQL: the tie-break has to be total, or a list
    # reshuffles between identical requests — the lesson `test_ranking.py` paid for.
    groups.sort(
        key=lambda g: (
            -g.totals.calls,
            g.provider,
            g.model,
            g.prompt_version,
            g.bucket.value,
        )
    )
    return groups


async def _quality(
    session: AsyncSession, *, candidate: Candidate, scope: UsageScope
) -> QualitySummary:
    """The guardrail's own numbers, over stored profiles."""
    query = select(
        func.count().label("profiles"),
        func.coalesce(func.sum(ExtractedProfileRow.claims_verified), 0).label("verified"),
        func.coalesce(func.sum(ExtractedProfileRow.claims_dropped), 0).label("dropped"),
        func.coalesce(func.sum(ExtractedProfileRow.attempts), 0).label("attempts"),
    )
    if scope is not UsageScope.ALL:
        query = query.join(Resume, Resume.id == ExtractedProfileRow.resume_id).where(
            Resume.candidate_id == candidate.id
        )

    row = (await session.execute(query)).one()

    claims = row.verified + row.dropped
    return QualitySummary(
        profiles=row.profiles,
        claims_verified=row.verified,
        claims_dropped=row.dropped,
        # From the totals, never the mean of the stored rates — see the schema.
        hallucination_rate=(row.dropped / claims) if claims else None,
        extraction_attempts_total=row.attempts,
    )


async def _parse_outcomes(
    session: AsyncSession, *, candidate: Candidate, scope: UsageScope
) -> list[ParseOutcome]:
    """How many documents rest in each status."""
    query = select(Resume.status, func.count().label("resumes")).group_by(Resume.status)
    if scope is not UsageScope.ALL:
        query = query.where(Resume.candidate_id == candidate.id)

    rows: Sequence[tuple[ResumeStatus, int]] = (await session.execute(query)).all()  # type: ignore[assignment]
    outcomes = [ParseOutcome(status=status, resumes=count) for status, count in rows]
    outcomes.sort(key=lambda o: (-o.resumes, o.status.value))
    return outcomes
