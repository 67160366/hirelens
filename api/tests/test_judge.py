"""Tests for requirement-level judging.

Where `test_extract.py` pins that nothing enters a profile uncited, this pins the
same rule for a *comparison*: a requirement reads `met` only because a quote was
located in the document, and the model is never the one that decides. The tests
that matter most here are the ones proving a fabrication cannot buy a verdict, and
that "the resume does not mention it" is never reported as "the candidate lacks it".
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

from app.llm.base import (
    LLMResponseError,
    LLMUnavailableError,
    LLMUsage,
    SchemaT,
    StructuredExtractor,
    StructuredResult,
)
from app.llm.fake import FakeExtractor, FakeMode
from app.pipeline.evidence import RejectReason
from app.pipeline.judge import judge_requirements
from app.pipeline.parse import ParsedDocument, parse_pdf
from app.schemas.extraction import RawExtraction
from app.schemas.judgment import (
    RawJudgment,
    RawRequirementMatch,
    RequirementSpec,
    Verdict,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def resume_en():
    return parse_pdf(FIXTURES / "resume_en.pdf")


@pytest.fixture(scope="module")
def resume_th():
    return parse_pdf(FIXTURES / "resume_th.pdf")


@pytest.fixture(scope="module")
def multipage():
    return parse_pdf(FIXTURES / "resume_multipage.pdf")


def spec(
    label: str,
    *,
    kind: str = "skill",
    must_have: bool = False,
    weight: float = 1.0,
) -> RequirementSpec:
    return RequirementSpec(
        id=f"req-{label}", label=label, kind=kind, must_have=must_have, weight=weight
    )


def verdicts(judgment) -> dict[str, Verdict]:
    return {item.label: item.verdict for item in judgment.requirements}


class ScriptedJudge(StructuredExtractor):
    """Returns canned judgments in order, for shapes the rule-based fake cannot pose."""

    provider_name: ClassVar[str] = "scripted"

    def __init__(self, *responses: RawJudgment) -> None:
        self._responses = list(responses)
        self.call_count = 0

    async def extract(
        self, *, system: str, user: str, schema: type[SchemaT]
    ) -> StructuredResult[SchemaT]:
        self.call_count += 1
        # Repeat the last response once the script runs out.
        index = min(self.call_count - 1, len(self._responses) - 1)
        usage = LLMUsage(provider=self.provider_name, model="scripted", cost_usd=0.0)
        return StructuredResult(value=self._responses[index], usage=usage)  # type: ignore[arg-type]


class TestFaithfulJudging:
    async def test_a_requirement_the_resume_shows_is_met_with_evidence(self, resume_en):
        outcome = await judge_requirements(
            resume_en, [spec("Python"), spec("PostgreSQL")], FakeExtractor()
        )
        assert verdicts(outcome.judgment) == {"Python": Verdict.MET, "PostgreSQL": Verdict.MET}
        assert all(item.evidence for item in outcome.judgment.requirements)

    async def test_a_requirement_the_resume_does_not_mention_is_not_evidenced(self, resume_en):
        outcome = await judge_requirements(resume_en, [spec("Kubernetes")], FakeExtractor())
        judged = outcome.judgment.requirements[0]

        assert judged.verdict is Verdict.NOT_EVIDENCED
        assert judged.evidence == []
        # The vocabulary itself is the guarantee: there is no way to say "not met".
        assert not hasattr(Verdict, "NOT_MET")

    async def test_every_evidence_offset_slices_back_to_its_quote(self, resume_en):
        """The offset contract, which judging inherits rather than reimplements."""
        outcome = await judge_requirements(
            resume_en,
            [spec("Python"), spec("Docker"), spec("Chulalongkorn University", kind="education")],
            FakeExtractor(),
        )
        references = [ref for item in outcome.judgment.requirements for ref in item.evidence]
        assert references

        for reference in references:
            assert resume_en.text[reference.char_start : reference.char_end] == reference.quote

    async def test_evidence_names_a_real_page(self, resume_en):
        outcome = await judge_requirements(resume_en, [spec("FastAPI")], FakeExtractor())
        for reference in outcome.judgment.requirements[0].evidence:
            assert 1 <= reference.page <= resume_en.page_count

    async def test_results_follow_the_requirement_order(self, resume_en):
        """A list that reshuffles between screenings is unreadable beside a job."""
        requirements = [spec("Redis"), spec("Kubernetes"), spec("Python")]
        outcome = await judge_requirements(resume_en, requirements, FakeExtractor())
        assert [item.label for item in outcome.judgment.requirements] == [
            "Redis",
            "Kubernetes",
            "Python",
        ]

    async def test_ranking_inputs_are_carried_through_untouched(self, resume_en):
        """`must_have` and `weight` are read by ranking (slice 4). Judging must pass
        them through without consulting them — whether a requirement is evidenced is
        a question about the document, not about how much anyone cares."""
        requirements = [
            spec("Python", must_have=True, weight=3.0),
            spec("Kubernetes", must_have=True, weight=9.0),
        ]
        outcome = await judge_requirements(resume_en, requirements, FakeExtractor())

        for judged, original in zip(outcome.judgment.requirements, requirements, strict=True):
            assert judged.requirement_id == original.id
            assert judged.must_have == original.must_have
            assert judged.weight == original.weight

    async def test_one_call_is_enough_when_the_model_behaves(self, resume_en):
        extractor = FakeExtractor()
        outcome = await judge_requirements(resume_en, [spec("Python")], extractor, max_attempts=3)
        assert extractor.call_count == 1
        assert outcome.judgment.stats.attempts == 1


class TestThaiJudging:
    async def test_a_thai_requirement_resolves_against_thai_text(self, resume_th):
        outcome = await judge_requirements(
            resume_th, [spec("การออกแบบระบบ"), spec("Python")], FakeExtractor()
        )
        assert verdicts(outcome.judgment) == {
            "การออกแบบระบบ": Verdict.MET,
            "Python": Verdict.MET,
        }

    async def test_thai_evidence_offsets_are_exact(self, resume_th):
        outcome = await judge_requirements(
            resume_th, [spec("จุฬาลงกรณ์มหาวิทยาลัย", kind="education")], FakeExtractor()
        )
        for reference in outcome.judgment.requirements[0].evidence:
            assert resume_th.text[reference.char_start : reference.char_end] == reference.quote


class TestTheVerdictIsDerived:
    """The heart of the milestone: the model cannot assert a verdict, only offer
    quotes, so a fabricated quote buys nothing."""

    async def test_a_fabricated_quote_cannot_produce_met(self, resume_en):
        outcome = await judge_requirements(
            resume_en,
            [spec("Python"), spec("Kubernetes")],
            FakeExtractor(FakeMode.HALLUCINATING),
            max_attempts=1,
        )
        # The fake attaches its fabrication to the requirement with no real evidence.
        assert verdicts(outcome.judgment) == {
            "Python": Verdict.MET,
            "Kubernetes": Verdict.NOT_EVIDENCED,
        }

    async def test_the_fabrication_is_recorded_rather_than_silently_dropped(self, resume_en):
        outcome = await judge_requirements(
            resume_en,
            [spec("Python"), spec("Kubernetes")],
            FakeExtractor(FakeMode.HALLUCINATING),
            max_attempts=1,
        )
        assert len(outcome.judgment.dropped) == 1
        dropped = outcome.judgment.dropped[0]
        assert dropped.reason is RejectReason.NOT_FOUND
        assert dropped.value == "Kubernetes"

    async def test_the_hallucination_rate_covers_judging_for_free(self, resume_en):
        """`EvidenceStats` is reused wholesale, so the metric needed no new code."""
        outcome = await judge_requirements(
            resume_en,
            [spec("Python"), spec("Kubernetes")],
            FakeExtractor(FakeMode.HALLUCINATING),
            max_attempts=1,
        )
        stats = outcome.judgment.stats
        assert stats.dropped == 1
        assert 0 < stats.hallucination_rate < 1
        assert stats.by_reject_reason == {RejectReason.NOT_FOUND: 1}

    async def test_a_quote_from_the_requirement_list_is_not_evidence(self, resume_en):
        """A model quoting the prompt back would otherwise mark everything met."""
        raw = RawJudgment(
            matches=[RawRequirementMatch(requirement=1, quotes=["Kubernetes administration"])]
        )
        outcome = await judge_requirements(
            resume_en, [spec("Kubernetes administration")], ScriptedJudge(raw), max_attempts=1
        )
        assert outcome.judgment.requirements[0].verdict is Verdict.NOT_EVIDENCED
        assert outcome.judgment.dropped[0].reason is RejectReason.NOT_FOUND

    async def test_a_too_short_quote_is_rejected_with_its_own_reason(self, resume_en):
        raw = RawJudgment(matches=[RawRequirementMatch(requirement=1, quotes=["Go"])])
        outcome = await judge_requirements(
            resume_en, [spec("Go")], ScriptedJudge(raw), max_attempts=1
        )
        assert outcome.judgment.requirements[0].verdict is Verdict.NOT_EVIDENCED
        assert outcome.judgment.dropped[0].reason is RejectReason.TOO_SHORT


class TestUnknownRequirementNumbers:
    """A number nobody asked about points at something that is not there — the same
    class of fabrication as a quote that is not there, and counted the same way."""

    async def test_an_out_of_range_number_is_dropped_and_named(self, resume_en):
        raw = RawJudgment(
            matches=[RawRequirementMatch(requirement=7, quotes=["Python, FastAPI, PostgreSQL"])]
        )
        outcome = await judge_requirements(
            resume_en, [spec("Python")], ScriptedJudge(raw), max_attempts=1
        )
        assert outcome.judgment.dropped[0].reason is RejectReason.UNKNOWN_REQUIREMENT
        assert outcome.judgment.stats.by_reject_reason == {RejectReason.UNKNOWN_REQUIREMENT: 1}

    async def test_zero_is_out_of_range_because_the_list_is_one_based(self, resume_en):
        """A model that 0-indexes must not silently answer about requirement 1."""
        raw = RawJudgment(
            matches=[RawRequirementMatch(requirement=0, quotes=["Python, FastAPI, PostgreSQL"])]
        )
        outcome = await judge_requirements(
            resume_en, [spec("Python")], ScriptedJudge(raw), max_attempts=1
        )
        assert outcome.judgment.requirements[0].verdict is Verdict.NOT_EVIDENCED
        assert outcome.judgment.dropped[0].reason is RejectReason.UNKNOWN_REQUIREMENT

    async def test_a_valid_number_beside_an_invalid_one_still_counts(self, resume_en):
        raw = RawJudgment(
            matches=[
                RawRequirementMatch(requirement=1, quotes=["Python, FastAPI, PostgreSQL"]),
                RawRequirementMatch(requirement=99, quotes=["Python, FastAPI, PostgreSQL"]),
            ]
        )
        outcome = await judge_requirements(
            resume_en, [spec("Python")], ScriptedJudge(raw), max_attempts=1
        )
        assert outcome.judgment.requirements[0].verdict is Verdict.MET
        assert len(outcome.judgment.dropped) == 1


class TestDuplicateNumbers:
    async def test_quotes_for_a_repeated_number_merge_rather_than_overwrite(self, resume_en):
        """Losing the second entry would throw away real, verifiable evidence."""
        raw = RawJudgment(
            matches=[
                RawRequirementMatch(requirement=1, quotes=["Python, FastAPI, PostgreSQL"]),
                RawRequirementMatch(
                    requirement=1, quotes=["Built payment reconciliation services in Python"]
                ),
            ]
        )
        outcome = await judge_requirements(
            resume_en, [spec("Python")], ScriptedJudge(raw), max_attempts=1
        )
        judged = outcome.judgment.requirements[0]
        assert judged.verdict is Verdict.MET
        assert len(judged.evidence) == 2


class TestShortLabels:
    async def test_a_label_shorter_than_the_quote_floor_still_resolves(self, resume_en):
        """`MIN_QUOTE_CHARS` rejects a quote under 4 characters, and real skills are
        that short ("Go", "AWS", "SQL"). The fake quotes the whole line the label
        sits on, which is what a model is told to do too, so the floor never bites
        a legitimate short requirement."""
        outcome = await judge_requirements(resume_en, [spec("Jan")], FakeExtractor())
        judged = outcome.judgment.requirements[0]

        assert judged.verdict is Verdict.MET
        assert judged.evidence[0].quote == "Acme Logistics — Backend Engineer (Jan 2021 - Mar 2024)"
        assert outcome.judgment.dropped == []


class TestEmptyRequirements:
    async def test_no_requirements_means_no_model_call(self, resume_en):
        """The empty case, checked on purpose. A call here could only answer
        "nothing", and this path runs once per resume per job."""
        extractor = FakeExtractor()
        outcome = await judge_requirements(resume_en, [], extractor)

        assert extractor.call_count == 0
        assert outcome.usages == []
        assert outcome.total_cost_usd == 0.0

    async def test_no_requirements_is_a_valid_empty_judgment(self, resume_en):
        outcome = await judge_requirements(resume_en, [], FakeExtractor())
        assert outcome.judgment.requirements == []
        assert outcome.judgment.dropped == []
        assert outcome.judgment.stats.total_claims == 0
        # Nothing claimed means nothing fabricated: 0, not undefined.
        assert outcome.judgment.stats.hallucination_rate == 0.0


class TestRetryLoop:
    async def test_a_clean_retry_is_preferred_over_a_dirty_first_attempt(self, resume_en):
        dirty = RawJudgment(
            matches=[RawRequirementMatch(requirement=1, quotes=["deep Kubernetes expertise"])]
        )
        clean = RawJudgment(
            matches=[RawRequirementMatch(requirement=1, quotes=["Python, FastAPI, PostgreSQL"])]
        )
        judge = ScriptedJudge(dirty, clean)

        outcome = await judge_requirements(resume_en, [spec("Python")], judge, max_attempts=2)

        assert judge.call_count == 2
        assert outcome.judgment.dropped == []
        assert outcome.judgment.requirements[0].verdict is Verdict.MET

    async def test_an_empty_retry_does_not_beat_a_first_attempt_that_proved_things(self, resume_en):
        """The one place judging must *not* copy `extract_profile`.

        The retry prompt tells the model to leave a requirement out rather than
        reword a rejected quote, so a compliant second attempt can answer about
        nothing at all and score zero rejections. On extraction's "fewest dropped"
        rule that empty answer would win and silently discard a requirement the
        first attempt had proven with a real citation.
        """
        proved_one = RawJudgment(
            matches=[
                RawRequirementMatch(requirement=1, quotes=["Python, FastAPI, PostgreSQL"]),
                RawRequirementMatch(requirement=2, quotes=["invented experience with Kafka"]),
            ]
        )
        gave_up = RawJudgment(matches=[])
        judge = ScriptedJudge(proved_one, gave_up)

        outcome = await judge_requirements(
            resume_en, [spec("Python"), spec("Kafka")], judge, max_attempts=2
        )

        assert judge.call_count == 2
        assert outcome.judgment.met_count == 1
        assert verdicts(outcome.judgment) == {
            "Python": Verdict.MET,
            "Kafka": Verdict.NOT_EVIDENCED,
        }

    async def test_attempts_reports_the_calls_actually_made(self, resume_en):
        judge = ScriptedJudge(
            RawJudgment(matches=[RawRequirementMatch(requirement=1, quotes=["never in the text"])])
        )
        outcome = await judge_requirements(resume_en, [spec("Python")], judge, max_attempts=3)
        assert judge.call_count == 3
        assert outcome.judgment.stats.attempts == 3


class TestPageMapping:
    """Judging resolves a quote against text parsed long ago, so the page it reports
    comes from `resumes.page_spans` rather than from a live parse."""

    async def test_a_restored_document_reports_the_real_page(self, multipage):
        restored = ParsedDocument.from_stored(multipage.text, multipage.stored_page_spans)
        raw = RawJudgment(
            matches=[
                RawRequirementMatch(
                    requirement=1, quotes=["Page 2 project 4: distinctive marker P2I4."]
                )
            ]
        )
        outcome = await judge_requirements(
            restored, [spec("marker P2I4")], ScriptedJudge(raw), max_attempts=1
        )
        assert outcome.judgment.requirements[0].evidence[0].page == 2

    async def test_a_row_written_before_the_migration_reports_page_one(self, multipage):
        """Null `page_spans` degrades to page 1 rather than failing the screening."""
        restored = ParsedDocument.from_stored(multipage.text, None)
        raw = RawJudgment(
            matches=[
                RawRequirementMatch(
                    requirement=1, quotes=["Page 2 project 4: distinctive marker P2I4."]
                )
            ]
        )
        outcome = await judge_requirements(
            restored, [spec("marker P2I4")], ScriptedJudge(raw), max_attempts=1
        )
        judged = outcome.judgment.requirements[0]
        assert judged.verdict is Verdict.MET
        assert judged.evidence[0].page == 1


class TestFailurePropagation:
    async def test_backend_outage_is_not_swallowed(self, resume_en):
        with pytest.raises(LLMUnavailableError):
            await judge_requirements(
                resume_en, [spec("Python")], FakeExtractor(FakeMode.UNAVAILABLE)
            )

    async def test_max_attempts_must_be_at_least_one(self, resume_en):
        with pytest.raises(ValueError, match="at least 1"):
            await judge_requirements(resume_en, [spec("Python")], FakeExtractor(), max_attempts=0)


class TestTheFakeAnswersBothSchemas:
    """`app/llm/fake.py` had to learn judging, or the suite and CI would need an API
    key — the property `docs/HANDOFF.md` §2 calls load-bearing."""

    async def test_it_still_answers_extractions(self, resume_en):
        result = await FakeExtractor().extract(
            system="", user=f"<resume>\n{resume_en.text}\n</resume>", schema=RawExtraction
        )
        assert isinstance(result.value, RawExtraction)

    async def test_it_answers_judgments(self, resume_en):
        result = await FakeExtractor().extract(
            system="",
            user=f"Requirements:\n1. [skill] Python\n\n<resume>\n{resume_en.text}\n</resume>",
            schema=RawJudgment,
        )
        assert isinstance(result.value, RawJudgment)
        assert result.value.matches[0].requirement == 1

    async def test_it_refuses_a_schema_it_does_not_produce(self):
        with pytest.raises(LLMResponseError, match="RawExtraction or RawJudgment"):
            await FakeExtractor().extract(system="", user="", schema=RequirementSpec)

    async def test_it_never_quotes_the_requirement_list(self, resume_en):
        """A requirement's own wording sits outside `<resume>`, so it cannot be
        mistaken for the document — the reason the prompt is laid out that way."""
        result = await FakeExtractor().extract(
            system="",
            user=(f"Requirements:\n1. [skill] Kubernetes\n\n<resume>\n{resume_en.text}\n</resume>"),
            schema=RawJudgment,
        )
        assert result.value.matches == []
