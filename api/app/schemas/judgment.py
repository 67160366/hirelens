"""Judging a resume against a job's requirements.

The twin of `extraction.py` + `profile.py`, and the same two layers: what the model
returns (quotes only) and what we keep (offsets, verdicts, stats).

**The model is never asked for a verdict.** It is asked only for quotes showing a
requirement *is* met, and to omit the requirement otherwise. The application derives
the rest: at least one quote that `EvidenceResolver` could locate is `met`, none is
`not_evidenced`, and every quote that failed lands in `dropped` and in the
hallucination rate. That is the same move as never asking for character offsets,
applied to judging — the one thing a model could assert unverifiably it is never
given the chance to say.

There is no `not_met`, on purpose. Absence cannot be quoted: you cannot cite text
that is not in a document, so "not met" would be exactly the unverifiable assertion
this project exists to refuse. It is also the honest label, because the system
cannot tell "the candidate lacks it" from "the resume does not mention it" — and one
of those is a statement about a person.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.profile import DroppedClaim, EvidenceRef, EvidenceStats


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RawRequirementMatch(_Strict):
    """The quotes the model offers for one requirement."""

    requirement: int = Field(
        description=(
            "The number of the requirement these quotes support, exactly as it is "
            "listed in the prompt."
        )
    )
    quotes: list[str] = Field(
        description=(
            "Text copied character-for-character from the resume that shows this "
            "requirement is met. Do not paraphrase, translate, reformat, or "
            "summarize. If the resume does not show it, omit this requirement "
            "entirely rather than sending an empty list."
        )
    )


class RawJudgment(_Strict):
    """The complete model response for one screening.

    Deliberately narrow, like `RawExtraction`: quotes and a requirement number, and
    nothing else. No verdict, no score, no confidence — all three are things the
    application derives or refuses to claim.

    Kept JSON-Schema-plain (no recursion, no string/number constraints) so the same
    models drive Gemini's `response_json_schema` and Anthropic's structured outputs
    without per-provider rewriting. That is why `requirement` carries no `ge=1`:
    range checking belongs in the verifier, with the rest of the guardrail.
    """

    matches: list[RawRequirementMatch] = Field(default_factory=list)


class RequirementSpec(BaseModel):
    """One requirement, as the pipeline sees it.

    A plain value object rather than the `JobRequirement` ORM row, so
    `app/pipeline/judge.py` stays free of the database exactly as `extract.py` is,
    and so its tests need no session. The screening service builds these from rows.

    `must_have` and `weight` are carried through untouched and read by **ranking**
    (M3 slice 4). Nothing in judging consults either: whether a requirement is met
    is a question about the document, not about how much anyone cares.
    """

    id: str
    label: str
    kind: str = "other"
    detail: str | None = None
    must_have: bool = False
    weight: float = 1.0


class Verdict(StrEnum):
    MET = "met"
    """At least one quote for this requirement was located in the document."""

    NOT_EVIDENCED = "not_evidenced"
    """Nothing citable was found. Deliberately *not* `not_met` — see the module
    docstring. The resume may simply not mention it."""


class RequirementJudgment(BaseModel):
    """One requirement's verdict, and the citations that produced it."""

    requirement_id: str
    label: str
    must_have: bool
    weight: float
    verdict: Verdict
    evidence: list[EvidenceRef] = Field(default_factory=list)
    """Empty exactly when the verdict is `not_evidenced` — the verdict is derived
    from this list, not asserted alongside it."""


class Judgment(BaseModel):
    """A screening as the system understands it, every `met` traceable to source."""

    requirements: list[RequirementJudgment] = Field(default_factory=list)
    dropped: list[DroppedClaim] = Field(default_factory=list)
    stats: EvidenceStats = Field(default_factory=EvidenceStats)

    @property
    def met_count(self) -> int:
        return sum(1 for item in self.requirements if item.verdict is Verdict.MET)
