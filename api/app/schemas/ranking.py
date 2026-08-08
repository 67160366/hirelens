"""Ordering candidates for one job, and saying who was left out and why.

The third layer in the same family as `extraction.py` -> `profile.py` and
`judgment.py`: what the model returns, what we store, and now what we *derive*.
Nothing here involves a model at all. Ranking is a pure function over screenings
that already exist, which is why changing a weight reorders a list for free
(`app/pipeline/ranking.py`).

**The rationale is the citation list, not the score.** `RankedEntry` carries every
`RequirementJudgment` — verdicts with the spans that produced them — rather than a
number and a promise. A ranking whose justification needs a second request invites
a UI that shows only the number, and a number nobody can check is precisely what
this project exists not to produce.

Nothing is silently dropped, for the same reason a rejected quote lands in
`dropped` rather than vanishing: a screening that could not be ranked is reported
in `excluded` with the reason it was skipped.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.judgment import RequirementJudgment


class ExclusionReason(StrEnum):
    """Why a screening is not in the ranked list."""

    STALE = "stale"
    """It answers an older set of requirements. Reported rather than re-run: a
    ranking that mixed two questions would be quietly meaningless, and re-running
    would spend a model call the caller never asked for. `POST /jobs/{id}/screenings`
    is where a caller chooses to pay for a fresh answer."""

    NOT_COMPLETED = "not_completed"
    """Queued, running, failed or dead-lettered — there is no verdict to rank yet.
    `status` carries which."""

    MALFORMED = "malformed"
    """Completed, current, and still unusable: no stored result, or a requirement
    count that disagrees with the job. Cannot happen through the normal path, and is
    reported instead of being ranked on a mismatched join."""


class ExcludedEntry(BaseModel):
    """A screening that exists but could not take part in the ranking."""

    screening_id: str
    resume_id: str
    status: str
    reason: ExclusionReason


class RankedEntry(BaseModel):
    """One resume's place in the order, and the evidence behind it."""

    rank: int = Field(description="1-based, assigned after sorting.")
    screening_id: str
    resume_id: str

    gate_passed: bool
    """Every `must_have` requirement is met. A candidate missing one ranks below
    every candidate that has them all, however well they score elsewhere — a gate
    rather than a heavy weight, which is what `JobRequirement.must_have` is for."""

    score: float
    """Weighted share of requirements met, in [0, 1]. Ordering *within* a tier only:
    it never lifts a candidate over the gate."""

    must_haves_met: int
    must_haves_total: int
    requirements_met: int
    requirements_total: int

    requirements: list[RequirementJudgment]
    """Every requirement with its verdict and citations — the actual rationale.

    Re-keyed against the job's *current* `must_have` and `weight` before it is
    returned, because the stored judgment froze both at judging time and neither is
    part of the screening's fingerprint. See `app/pipeline/ranking.py`."""


class Ranking(BaseModel):
    """Every screening for one job: those that could be ordered, and those that could not."""

    ranked: list[RankedEntry] = Field(default_factory=list)
    excluded: list[ExcludedEntry] = Field(default_factory=list)
