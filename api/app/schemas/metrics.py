"""What the usage and quality dashboard reports, and the rules it reports under.

M5 slice 2. The organizing idea, the same shape as M3's "a verdict is derived from a
located quote" and M4's "a state is a projection of an event log": **every number here
is a query over rows the system already wrote, and can name the rows it came from.**
Cite your source, applied to metrics.

So every aggregate below carries the row count behind it. A figure whose denominator is
invisible is a claim without a citation, which is the thing this project exists not to
produce — and it is what makes "42 calls" and "42 calls, of which 3 had no price"
different statements rather than the same one rounded differently.

**Nothing here spends a model call.** The dashboard reports; it never re-asks. The
schema was shaped for exactly this in M1 — `extracted_profiles` lifts
`claims_verified`, `claims_dropped` and `hallucination_rate` into real columns
*specifically* so this is a `GROUP BY` and not a JSON walk, and `models/core.py` has
said so in a docstring since then.

**This was specified as a *cost* dashboard, and was respecified with the owner on
2026-08-15 because there is no cost.** `app/llm/gemini.py` maps every model to
`FREE_TIER`, so all logged calls store `cost_usd = 0.0` and not one is `NULL` — the
single behaviour the original spec said it had to get right is unreachable on real
data. Charting it would have shipped a screen of zeroes that reads as a bug. The cost
*rule* survives here in full (see `CallTotals.cost_usd`) against the day a paid
provider lands; what the screen leads with is tokens, latency and quality, which are
real today.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.models import ResumeStatus


class CallBucket(StrEnum):
    """Which piece of work paid for a model call.

    `LLMCallLog` sets `resume_id` **xor** `screening_id` — a call belongs to the work
    that paid for it, and a screening is not a resume. Keeping the two apart is what
    makes "what did extracting this document cost" and "what did screening this
    candidate cost" separately answerable, so the dashboard must never collapse them.

    The last two buckets exist because **that invariant is a docstring, not a
    constraint** (found 2026-08-15): both columns are nullable and nothing enforces the
    xor, so a row with neither — or with both — is legal today. Bucketing them
    explicitly is the same instinct as `dropped` and `excluded`: a row the system
    cannot attribute is *reported*, never silently absent from a total. Together the
    four buckets partition the rows exactly, which `test_metrics.py` asserts.
    """

    EXTRACTION = "extraction"
    """`resume_id` set, `screening_id` null. Building a profile from a document."""

    JUDGING = "judging"
    """`screening_id` set, `resume_id` null. Judging a document against requirements."""

    UNATTRIBUTED = "unattributed"
    """Neither set. Cannot happen through any shipped path, and would vanish from every
    owner-scoped total if it were not named — which is why it is named."""

    AMBIGUOUS = "ambiguous"
    """Both set. Also unreachable today, and it would be *double* counted rather than
    lost, so it is worth telling apart from the row that is merely missing."""


class CallTotals(BaseModel):
    """One group of model calls, summed.

    Used both per bucket and per `(provider, model, prompt_version)` group, because the
    same question — what did these calls consume — is being asked at two grains.
    """

    calls: int = Field(description="How many rows produced every figure in this group.")

    input_tokens: int
    output_tokens: int
    cached_input_tokens: int

    latency_ms_total: int
    latency_ms_mean: float | None = Field(
        default=None,
        description="Null when there are no calls, rather than a zero that reads as 'instant'.",
    )

    calls_priced: int = Field(
        description=(
            "How many of `calls` carry a known `cost_usd`. Exposed rather than implied, "
            "so a reader can see why `cost_usd` is null."
        )
    )

    cost_usd: float | None = Field(
        default=None,
        description=(
            "Null unless EVERY call in the group has a known price. SQL SUM() skips "
            "nulls, so summing a group where some prices are unknown yields a number "
            "that looks complete and is not — the same class of silent corruption as a "
            "stale price table, which CLAUDE.md names as a hazard. A partial total is "
            "worse than no total, because only one of them is obviously missing."
        ),
    )

    @property
    def cost_is_complete(self) -> bool:
        return self.calls_priced == self.calls


class CallGroup(BaseModel):
    """Calls grouped by who served them and which prompt asked.

    `prompt_version` is the axis that makes this worth showing: comparing prompt
    revisions is guesswork without it, which is why `LLMCallLog` stores it at all.
    """

    provider: str
    model: str
    prompt_version: str
    bucket: CallBucket
    totals: CallTotals


class QualitySummary(BaseModel):
    """The guardrail's own numbers, over stored profiles.

    This is the metric that costs nothing to produce — no labelled dataset, no baseline
    to beat — because verification already happens on every document.
    """

    profiles: int = Field(description="How many extracted profiles are behind these figures.")
    claims_verified: int
    claims_dropped: int

    hallucination_rate: float | None = Field(
        default=None,
        description=(
            "Recomputed from the totals — dropped / (verified + dropped) — and NOT the "
            "mean of the stored per-profile rates. Averaging rates weights a one-claim "
            "document the same as a thirty-claim one, which is a different statistic "
            "wearing this one's name. Null when there are no claims at all, rather "
            "than a 0.0 that would read as 'nothing was fabricated'."
        ),
    )

    extraction_attempts_total: int = Field(
        description=(
            "Model calls the re-ask loop spent, summed from `extracted_profiles.attempts`. "
            "This is the *stats* counter, not `Resume.attempts`, which is the job counter "
            "and means something else entirely despite the identical spelling."
        )
    )


class ParseOutcome(BaseModel):
    """How many resumes rest in each status. Parse success, without a new table."""

    status: ResumeStatus
    resumes: int


class UsageScope(StrEnum):
    """Whose rows a report covers."""

    OWN = "own"
    """The caller's own. Export is a subject-access request rather than a dump of
    everything visible, and the same instinct applies to a metric: a recruiter may
    *read* an applicant's resume without that document's extraction cost being theirs
    to total."""

    ALL = "all"
    """Every row in the system. `ADMIN` only, decided with the owner on 2026-08-15.

    Note this is a *row scope*, not a route gate, and the two are not interchangeable:
    `require_role` runs no query and returns the caller unchanged, so it can refuse a
    route but cannot widen a query. The role is therefore read here, in the WHERE
    clause, the way `_owned_resume` reads it."""


class UsageReport(BaseModel):
    """Everything the dashboard renders, in one response.

    One request rather than one per panel, for the reason `GET /jobs/{id}/ranking`
    returns verdicts *with* their citations: a screen that needs a second request per
    figure invites a screen that shows the figure without it.
    """

    scope: UsageScope
    generated_at: datetime

    totals: CallTotals = Field(
        description="Every model call in scope, whatever bucket it landed in."
    )
    by_bucket: dict[CallBucket, CallTotals] = Field(
        description=(
            "Totals per bucket. Every bucket is present, including the empty ones — an "
            "absent key and a zero are different claims, and only one of them says "
            "'we looked'."
        )
    )
    by_group: list[CallGroup] = Field(
        description="Provider, model and prompt version, ordered by call count descending."
    )

    quality: QualitySummary
    parse_outcomes: list[ParseOutcome] = Field(
        description="Ordered by count descending. Statuses with no rows are omitted."
    )
