"""Judging against a real model, which the rest of the suite never does.

`test_judge.py` drives the whole path through `FakeExtractor`, which pins the
verdict derivation, the drop accounting, the numbering contract and the retry
loop — everything the *application* is responsible for. What it cannot pin is the
half the application does not control: the fake matches a requirement label by
substring, so under it a requirement worded differently from the document always
comes back `not_evidenced`. Real screening is mostly that case. A recruiter types
"a bachelor's degree in engineering"; the resume says "B.Eng Computer Engineering".

So this module asks a real model the questions only a real model can answer:

*   does semantic matching actually happen, and does the quote it returns still
    resolve against the document?
*   told to omit a requirement it cannot evidence, does it omit it — rather than
    stretching an unrelated quote to cover it?
*   does the 1-based numbering contract survive contact, or does the model
    renumber, 0-index, or invent numbers?
*   and above all: does the guardrail hold? Every span a real model produces must
    slice back out of the document character for character, or be dropped.

**Opt-in on `TEST_LIVE_LLM`, not on the presence of a key.** The key is in `.env`
on any machine set up for development, so gating on the key would quietly turn
every `pytest -q` into a billed run. `conftest.py` builds `Settings(_env_file=None)`
to keep the suite hermetic for exactly this reason; this module deliberately does
the opposite, and says so:

    TEST_LIVE_LLM=1 pytest tests/test_judge_live.py -q

Two documents, one call each. These assertions are about properties rather than
exact output — a model is not deterministic and pinning its wording would make this
a flaky test of nothing.
"""

from __future__ import annotations

import os

import pytest

from app.config import LLMProvider, Settings
from app.llm.registry import build_extractor
from app.pipeline.evidence import RejectReason
from app.pipeline.judge import judge_requirements
from app.pipeline.parse import ParsedDocument, parse_pdf
from app.schemas.judgment import RequirementSpec, Verdict
from tests.conftest import FIXTURES

TEST_LIVE_LLM = os.environ.get("TEST_LIVE_LLM", "")

pytestmark = pytest.mark.skipif(
    not TEST_LIVE_LLM,
    reason="Set TEST_LIVE_LLM=1 to run these against a real provider (spends quota).",
)


def _settings() -> Settings:
    """Read the developer's `.env`, unlike every other module in this suite.

    The provider and its key have to come from somewhere real, and `.env` is where
    this project keeps them. `pytestmark` above is what stops that from leaking into
    an ordinary run.
    """
    return Settings(llm_provider=LLMProvider.GEMINI)


@pytest.fixture(scope="module")
def extractor():
    settings = _settings()
    if not settings.gemini_api_key:
        pytest.skip("TEST_LIVE_LLM is set but GEMINI_API_KEY is empty.")
    return build_extractor(settings)


def _stored(path: str) -> ParsedDocument:
    """Parse, then rebuild from what a resume *row* would hold.

    Screening never has a live `ParsedDocument`; it has `document_text` and
    `page_spans`. Judging through `from_stored` here means the live run exercises
    the same object a screening will.
    """
    document = parse_pdf(FIXTURES / path)
    return ParsedDocument.from_stored(document.text, document.stored_page_spans)


def specs(*items: tuple[str, str]) -> list[RequirementSpec]:
    return [
        RequirementSpec(id=f"live-{index}", kind=kind, label=label)
        for index, (kind, label) in enumerate(items)
    ]


# Worded so that no label is a substring of the document — except "Python", which is
# the control. If these resolved by literal matching the module would prove nothing.
ENGLISH_REQUIREMENTS = specs(
    ("skill", "Python"),
    ("experience", "Backend engineering at a logistics company"),
    ("education", "A bachelor's degree in an engineering discipline"),
    ("skill", "Kubernetes cluster administration"),
    ("language", "Fluent Japanese"),
)

THAI_REQUIREMENTS = specs(
    ("education", "ปริญญาตรีวิศวกรรมคอมพิวเตอร์"),
    ("skill", "การออกแบบระบบ"),
    ("language", "ภาษาญี่ปุ่น"),
)


@pytest.fixture(scope="module")
async def english(extractor):
    document = _stored("resume_en.pdf")
    outcome = await judge_requirements(document, ENGLISH_REQUIREMENTS, extractor)
    return document, outcome.judgment


@pytest.fixture(scope="module")
async def thai(extractor):
    document = _stored("resume_th.pdf")
    outcome = await judge_requirements(document, THAI_REQUIREMENTS, extractor)
    return document, outcome.judgment


def _by_label(judgment) -> dict[str, object]:
    return {item.label: item for item in judgment.requirements}


class TestTheGuardrailHoldsAgainstARealModel:
    """The assertions that would matter most if they ever failed."""

    async def test_every_span_slices_back_out_of_the_document(self, english):
        document, judgment = english
        references = [ref for item in judgment.requirements for ref in item.evidence]
        assert references, "expected a real model to evidence something"

        for reference in references:
            assert document.text[reference.char_start : reference.char_end] == reference.quote

    async def test_no_requirement_is_met_without_evidence(self, english):
        _, judgment = english
        for item in judgment.requirements:
            assert (item.verdict is Verdict.MET) == bool(item.evidence)

    async def test_every_cited_page_is_a_page_the_document_has(self, english):
        document, judgment = english
        for item in judgment.requirements:
            for reference in item.evidence:
                assert 1 <= reference.page <= max(document.page_count, 1)


class TestSemanticMatching:
    """The reason this module exists: the fake cannot do any of this."""

    async def test_a_requirement_worded_unlike_the_document_still_resolves(self, english):
        document, judgment = english
        lowered = document.text.casefold()

        semantic = [
            item
            for item in judgment.requirements
            if item.verdict is Verdict.MET and item.label.casefold() not in lowered
        ]
        assert semantic, (
            "no requirement was matched semantically — every `met` label appears "
            "verbatim in the document, which is all the fake can do"
        )

    async def test_the_experience_requirement_cites_the_role_line(self, english):
        """ "Backend engineering at a logistics company" is nowhere in the text; the
        line that shows it is `Acme Logistics — Backend Engineer (...)`."""
        _, judgment = english
        item = _by_label(judgment)["Backend engineering at a logistics company"]

        assert item.verdict is Verdict.MET
        assert any("Acme Logistics" in ref.quote for ref in item.evidence)


class TestAbsenceIsNeverAsserted:
    async def test_a_requirement_the_resume_lacks_comes_back_not_evidenced(self, english):
        _, judgment = english
        for label in ("Kubernetes cluster administration", "Fluent Japanese"):
            item = _by_label(judgment)[label]
            assert item.verdict is Verdict.NOT_EVIDENCED
            assert item.evidence == []

    async def test_the_model_does_not_stretch_a_quote_to_cover_a_gap(self, english):
        """The failure this would catch: citing *something* for every requirement
        because a model dislikes returning nothing."""
        _, judgment = english
        assert judgment.met_count < len(judgment.requirements)


class TestTheNumberingContractSurvives:
    async def test_the_model_never_names_a_requirement_that_does_not_exist(self, english):
        """A renumbering or 0-indexing model would show up here, not as a crash."""
        _, judgment = english
        assert RejectReason.UNKNOWN_REQUIREMENT not in judgment.stats.by_reject_reason

    async def test_results_come_back_in_the_order_they_were_asked(self, english):
        _, judgment = english
        assert [item.label for item in judgment.requirements] == [
            spec.label for spec in ENGLISH_REQUIREMENTS
        ]


class TestThai:
    async def test_a_thai_requirement_matches_differently_worded_thai_text(self, thai):
        """`ปริญญาตรีวิศวกรรมคอมพิวเตอร์` is not in the document; the degree line
        reads `วิศวกรรมศาสตรบัณฑิต สาขาวิศวกรรมคอมพิวเตอร์`."""
        document, judgment = thai
        item = _by_label(judgment)["ปริญญาตรีวิศวกรรมคอมพิวเตอร์"]

        assert item.verdict is Verdict.MET
        assert item.label not in document.text

    async def test_thai_spans_slice_back_out_exactly(self, thai):
        """Thai is where an offset bug would surface first — combining marks make
        every naive index arithmetic wrong."""
        document, judgment = thai
        references = [ref for item in judgment.requirements for ref in item.evidence]
        assert references

        for reference in references:
            assert document.text[reference.char_start : reference.char_end] == reference.quote

    async def test_a_language_the_resume_never_mentions_is_not_evidenced(self, thai):
        _, judgment = thai
        assert _by_label(judgment)["ภาษาญี่ปุ่น"].verdict is Verdict.NOT_EVIDENCED
