"""Judge a resume against a job's requirements, citing every match.

The twin of `extract.py`, and the project's promise applied one step further:

    text -> ask the model for quotes -> locate every quote -> *derive* the verdict

The model is never asked whether a requirement is met. It is asked only for quotes
showing that it is, and the verdict falls out of what `EvidenceResolver` could
locate: `met` when at least one quote resolved, `not_evidenced` when none did. A
quote that cannot be located is a fabrication — dropped, reported, and counted in
the hallucination rate, exactly as in extraction and by exactly the same code.

There is no `not_met`. Absence cannot be quoted, so asserting it would be the one
unverifiable claim this design exists to refuse (`app/schemas/judgment.py`).

Two deliberate departures from `extract.py`, both explained where they happen: the
retry loop keeps the attempt with the most *met* requirements rather than simply the
fewest rejections, and an empty requirement list never reaches the model at all.
Everything else is shared rather than mirrored — `pipeline/verification.py` holds
the resolve-and-tally loop both modules run.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass

from app.llm.base import LLMUsage, StructuredExtractor
from app.pipeline.evidence import RejectReason
from app.pipeline.parse import ParsedDocument
from app.pipeline.prompts import (
    JUDGMENT_SYSTEM,
    build_judgment_retry_prompt,
    build_judgment_user_prompt,
)
from app.pipeline.verification import EvidenceRecorder
from app.schemas.judgment import (
    Judgment,
    RawJudgment,
    RequirementJudgment,
    RequirementSpec,
    Verdict,
)
from app.schemas.profile import EvidenceRef

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class JudgmentOutcome:
    """A verified judgment plus what it cost to produce."""

    judgment: Judgment
    usages: list[LLMUsage]

    @property
    def total_cost_usd(self) -> float | None:
        """None when any call's price is unknown — better than a misleading sum."""
        if any(usage.cost_usd is None for usage in self.usages):
            return None
        return sum(usage.cost_usd or 0.0 for usage in self.usages)

    @property
    def total_latency_ms(self) -> int:
        return sum(usage.latency_ms for usage in self.usages)


class _JudgmentVerifier:
    """Resolves one raw judgment against one document."""

    def __init__(self, document: ParsedDocument, requirements: list[RequirementSpec]) -> None:
        self._requirements = requirements
        self._evidence = EvidenceRecorder(document)

    def _group_by_requirement(self, raw: RawJudgment) -> dict[int, list[str]]:
        """Collect quotes per requirement number, refusing numbers nobody asked for.

        Two things happen here that a looser implementation would get wrong.

        A number outside the list is not a typo to be guessed at — the quotes under
        it cannot be attributed to anything, so they are dropped as
        `UNKNOWN_REQUIREMENT` rather than discarded quietly. Pointing at a
        requirement that does not exist is the same class of fabrication as quoting
        text that is not there, and it belongs in the same counter.

        Duplicate numbers **merge**. A model that splits its answer for one
        requirement across two entries has still answered about that requirement,
        and letting the later entry overwrite the earlier one would lose real,
        verifiable evidence without saying so.
        """
        grouped: dict[int, list[str]] = {}

        for match in raw.matches:
            if not 1 <= match.requirement <= len(self._requirements):
                for quote in match.quotes:
                    self._evidence.reject(
                        field=f"matches[requirement={match.requirement}]",
                        value=f"requirement {match.requirement}",
                        quote=quote,
                        reason=RejectReason.UNKNOWN_REQUIREMENT,
                    )
                continue

            grouped.setdefault(match.requirement, []).extend(match.quotes)

        return grouped

    def verify(self, raw: RawJudgment, *, attempts: int) -> Judgment:
        grouped = self._group_by_requirement(raw)
        judged: list[RequirementJudgment] = []

        for number, requirement in enumerate(self._requirements, start=1):
            evidence: list[EvidenceRef] = []
            for quote in grouped.get(number, []):
                reference = self._evidence.reference(
                    field=f"requirements[{number - 1}]", value=requirement.label, quote=quote
                )
                if reference is not None:
                    evidence.append(reference)

            judged.append(
                RequirementJudgment(
                    requirement_id=requirement.id,
                    label=requirement.label,
                    must_have=requirement.must_have,
                    weight=requirement.weight,
                    # Read off the evidence, never taken from the model. This one
                    # line is the whole reason the milestone is shaped this way.
                    verdict=Verdict.MET if evidence else Verdict.NOT_EVIDENCED,
                    evidence=evidence,
                )
            )

        return Judgment(
            requirements=judged,
            dropped=self._evidence.dropped,
            stats=self._evidence.stats(attempts=attempts),
        )


def requirements_fingerprint(requirements: list[RequirementSpec]) -> str:
    """Identify what the judge was shown, so a stored result can report itself stale.

    Covers exactly the fields that reach the prompt — `kind`, `label`, `detail` —
    **and their order**, because the model is asked to refer back to requirements by
    position and a reorder is therefore a different question.

    Excludes `must_have` and `weight` on purpose. Neither is in the prompt, so
    neither can change a verdict; they are ranking's inputs. Folding them in would
    invalidate a screening that is still perfectly correct every time someone
    adjusts a weight, and re-running it would spend a model call to reproduce the
    same answer.

    Ids are excluded too: deleting a requirement and typing the identical one back
    asks the same question of the same document.
    """
    payload = json.dumps(
        [[item.kind, item.label, item.detail or ""] for item in requirements],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_better(candidate: Judgment, incumbent: Judgment) -> bool:
    """Prefer more requirements met; break ties on fewer rejected quotes.

    `extract_profile` simply keeps the attempt with the fewest rejections, which is
    right for a profile because every field is independent. It is wrong here. The
    retry prompt tells the model to leave a requirement out rather than reword a
    rejected quote, so a compliant second attempt can answer about *fewer*
    requirements and score zero rejections — and on the extraction rule that empty
    answer would win, silently throwing away requirements the first attempt had
    proven with real citations.
    """
    if candidate.met_count != incumbent.met_count:
        return candidate.met_count > incumbent.met_count
    return candidate.stats.dropped < incumbent.stats.dropped


async def judge_requirements(
    document: ParsedDocument,
    requirements: list[RequirementSpec],
    extractor: StructuredExtractor,
    *,
    max_attempts: int = 2,
) -> JudgmentOutcome:
    """Judge every requirement against one document, re-asking about bad quotes.

    One model call carries the whole document and the whole requirement list — not
    one call per requirement. Requirement count times resume count is this
    milestone's cost multiplier, and this is the side of it that stays flat.

    Never returns a `met` that is not backed by a located quote.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    if not requirements:
        # Nothing to judge. A call here could only ever come back empty, so making
        # it would be spending money to be told so — and on a screening path that
        # runs once per resume per job, "only when there is a question" is the
        # difference between a bill and a rounding error.
        return JudgmentOutcome(judgment=Judgment(), usages=[])

    usages: list[LLMUsage] = []
    best: Judgment | None = None

    for attempt in range(1, max_attempts + 1):
        if attempt == 1 or best is None:
            user_prompt = build_judgment_user_prompt(document.text, requirements)
        else:
            user_prompt = build_judgment_retry_prompt(
                document.text, requirements, [claim.quote for claim in best.dropped]
            )

        result = await extractor.extract(
            system=JUDGMENT_SYSTEM, user=user_prompt, schema=RawJudgment
        )
        usages.append(result.usage)

        candidate = _JudgmentVerifier(document, requirements).verify(result.value, attempts=attempt)
        logger.debug(
            "judging attempt %d/%d: %d/%d met, %d verified, %d dropped",
            attempt,
            max_attempts,
            candidate.met_count,
            len(requirements),
            candidate.stats.verified,
            candidate.stats.dropped,
        )

        if best is None or _is_better(candidate, best):
            best = candidate

        if candidate.stats.dropped == 0:
            break

    if best is None:  # unreachable: max_attempts >= 1 guarantees one pass
        raise RuntimeError("judging produced no result")
    # Report the number of calls actually made, not the attempt that won.
    best.stats.attempts = len(usages)
    return JudgmentOutcome(judgment=best, usages=usages)
