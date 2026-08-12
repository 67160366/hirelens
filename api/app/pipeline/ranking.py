"""Order the candidates screened against one job.

`judge.py`'s downstream twin, and deliberately much smaller: **no model call, no
new table, no stored result.** Every input already exists — a `Screening` holds each
requirement's verdict and citations, and `JobRequirement` holds `must_have` and
`weight`, which judging has carried untouched since it was written precisely so this
module could read them. A ranking is computed on read, which is what makes adjusting
a weight free.

ORM-free like `judge.py`, and for the same reason: `ScreeningView` and
`RequirementSpec` go in, a `Ranking` comes out, and the tests need neither a
database nor a session.

Two rules shape the whole file.

**Weights come from the job as it is now, never from the stored judgment.**
`RequirementJudgment` persists `must_have` and `weight` as they were when the model
was called, but `requirements_fingerprint` deliberately excludes both — so editing a
weight leaves the screening *current* while the stored JSON keeps the old number
forever. Reading weights off the stored result is the obvious implementation, and it
silently makes weight edits do nothing at all.

**The join is by position, not by id.** The fingerprint excludes ids on purpose
(deleting a requirement and typing the identical one back asks the same question), so
a current screening can carry ids the job no longer has. What the fingerprint *does*
cover is `(kind, label, detail)` and their order — and `_JudgmentVerifier.verify`
emits exactly one judgment per requirement, in requirement order. So for the rows this
module actually ranks, index `i` on both sides is the same requirement. A length
mismatch means that invariant broke, and the row is excluded rather than joined
against something else.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.schemas.judgment import Judgment, RequirementJudgment, RequirementSpec, Verdict
from app.schemas.ranking import (
    ExcludedEntry,
    ExclusionReason,
    RankedEntry,
    Ranking,
)


@dataclass(frozen=True, slots=True)
class ScreeningView:
    """One screening as ranking sees it — a plain value object, no ORM.

    `completed` is passed in rather than inferred from `status` so this module never
    has to know the `ScreeningStatus` vocabulary; `status` itself is carried only to
    report it back on an exclusion. Same seam as `RequirementSpec`.
    """

    id: str
    resume_id: str
    status: str
    completed: bool
    requirements_hash: str | None
    prompt_version: str | None
    judgment: Judgment | None

    resume_filename: str | None = None
    """Display only, and last because nothing here reads it — the same standing as
    `status`, which is carried purely to report it back on an exclusion.

    It exists for one reason: the web client used to join the filename from
    `GET /resumes`, which returns the *caller's* resumes. True while every screened
    resume was theirs, and wrong the moment an application puts somebody else's in
    the list. Optional so a caller that does not need it — every test of the
    ordering — is not made to supply one."""


def rank_screenings(
    screenings: Sequence[ScreeningView],
    requirements: Sequence[RequirementSpec],
    *,
    requirements_hash: str,
    prompt_version: str,
) -> Ranking:
    """Order the screenings that answer the current requirements; report the rest.

    `requirements_hash` and `prompt_version` describe the job *now*. A completed
    screening disagreeing with either is stale — it was true of what it saw, so it is
    excluded and reported rather than deleted, silently recomputed, or ranked beside
    answers to a different question.
    """
    ranked: list[RankedEntry] = []
    excluded: list[ExcludedEntry] = []

    for screening in screenings:
        judgment = screening.judgment
        reason = _exclusion_reason(
            screening,
            requirements,
            requirements_hash=requirements_hash,
            prompt_version=prompt_version,
        )

        if reason is None and judgment is not None:
            ranked.append(_score(screening, judgment, requirements))
            continue

        excluded.append(
            ExcludedEntry(
                screening_id=screening.id,
                resume_id=screening.resume_id,
                resume_filename=screening.resume_filename,
                status=screening.status,
                # A missing judgment is the only way to arrive here without a
                # reason, and `_exclusion_reason` already calls that malformed.
                reason=reason or ExclusionReason.MALFORMED,
            )
        )

    # Ascending on every key: `not gate_passed` puts True (0) first, the negated
    # numbers put the largest first, and the id makes the order *total* — without it
    # two identically-scoring candidates could swap places between runs, and a list
    # that reshuffles on refresh is unusable.
    ranked.sort(
        key=lambda entry: (
            not entry.gate_passed,
            -entry.score,
            -entry.requirements_met,
            entry.screening_id,
        )
    )

    for position, entry in enumerate(ranked, start=1):
        entry.rank = position

    return Ranking(ranked=ranked, excluded=excluded)


def _exclusion_reason(
    screening: ScreeningView,
    requirements: Sequence[RequirementSpec],
    *,
    requirements_hash: str,
    prompt_version: str,
) -> ExclusionReason | None:
    """Why this screening cannot be ranked, or `None` if it can."""
    if not screening.completed:
        return ExclusionReason.NOT_COMPLETED

    if (
        screening.requirements_hash != requirements_hash
        or screening.prompt_version != prompt_version
    ):
        return ExclusionReason.STALE

    if screening.judgment is None:
        return ExclusionReason.MALFORMED

    # The positional join is only sound when both sides describe the same list. A
    # current screening should always satisfy this; if it does not, the invariant
    # this module rests on has broken and joining anyway would attach one
    # requirement's verdict to another's weight.
    if len(screening.judgment.requirements) != len(requirements):
        return ExclusionReason.MALFORMED

    return None


def _score(
    screening: ScreeningView, judgment: Judgment, requirements: Sequence[RequirementSpec]
) -> RankedEntry:
    """Re-key one judgment onto the current requirements and measure it."""
    rekeyed = [
        RequirementJudgment(
            requirement_id=spec.id,
            label=spec.label,
            # From the job as it is now — the whole point of this module.
            must_have=spec.must_have,
            weight=spec.weight,
            # From the screening: only the model's evidence decided these, and
            # nothing here may revisit a verdict.
            verdict=judged.verdict,
            evidence=judged.evidence,
        )
        for spec, judged in zip(requirements, judgment.requirements, strict=True)
    ]

    met = [item for item in rekeyed if item.verdict is Verdict.MET]
    must_haves = [item for item in rekeyed if item.must_have]
    must_haves_met = [item for item in must_haves if item.verdict is Verdict.MET]

    total_weight = sum(item.weight for item in rekeyed)
    met_weight = sum(item.weight for item in met)

    return RankedEntry(
        # Overwritten once the list is sorted; a rank means nothing before then.
        rank=0,
        screening_id=screening.id,
        resume_id=screening.resume_id,
        resume_filename=screening.resume_filename,
        # Vacuously true for a job with no must-haves, which is the right answer:
        # nothing was required, so nothing is missing.
        gate_passed=len(must_haves_met) == len(must_haves),
        # Must-haves count toward the score as well as gating. Within the passing
        # tier that is a constant and changes no order; within the failing tier it
        # is what puts "missing one of three" above "missing all three". It also
        # keeps the denominator non-zero when every requirement is a must-have.
        score=round(met_weight / total_weight, 6) if total_weight > 0 else 0.0,
        must_haves_met=len(must_haves_met),
        must_haves_total=len(must_haves),
        requirements_met=len(met),
        requirements_total=len(rekeyed),
        requirements=rekeyed,
    )
