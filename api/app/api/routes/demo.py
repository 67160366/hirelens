"""The public demo: the guardrail, run on request for somebody with no account.

**The second router that resolves no account**, after `careers.py` — and a
different kind of thing from it. `careers.py` publishes rows the company wrote;
this publishes *behaviour*. A visitor who has not applied to anything can watch a
quote be located in a document, and watch an invented one be refused, on the same
code path a real screening runs.

Three properties hold here, and each is pinned in `tests/test_demo.py` rather
than promised:

- **It writes nothing.** No session, no rows, no `llm_call_logs`. A demo is not a
  screening: nobody applied, nobody is being judged, and a visitor must not be
  able to add rows to the database by reloading a page.
- **It spends nothing.** The extractor is `FakeExtractor`, built here rather than
  taken from `app.state`, so the demo neither depends on nor bills whatever
  provider the deployment is configured with. That is also what makes it
  deterministic enough to write copy around.
- **It fabricates through the real path.** `FakeMode.HALLUCINATING` attaches a
  quote that is not in the document, and `judge_requirements` drops it through
  `EvidenceResolver` — the same module every verdict in this system rests on. A
  canned "here is what a refusal would look like" would be the one screen in this
  product asserting something it had not verified.

**One model call, not the usual two.** The production path re-asks once about
dropped quotes (`judge_requirements(max_attempts=2)`); here the fake backend is
deterministic, so a second ask fabricates the identical quote and the only visible
effect is a call count nobody can interpret. The demo shows what happens to one
answer, and the page says in words that the real path asks again.
"""

from __future__ import annotations

from enum import StrEnum

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.demo import (
    DEMO_DOCUMENT_TEXT,
    DEMO_FILENAME,
    DEMO_POSTING_TITLE,
    DEMO_REQUIREMENTS,
)
from app.llm.fake import FakeExtractor, FakeMode
from app.pipeline.judge import judge_requirements
from app.pipeline.parse import ParsedDocument
from app.schemas.judgment import Verdict
from app.schemas.profile import DroppedClaim, EvidenceRef

router = APIRouter(prefix="/demo", tags=["demo"])


class DemoMode(StrEnum):
    """Which model the visitor wants to watch."""

    FAITHFUL = "faithful"
    """Quotes every claim out of the document, the way a working provider does."""

    FABRICATING = "fabricating"
    """Attaches one quote that is not in the document, so the refusal is visible."""


class DemoRequirementOut(BaseModel):
    """One requirement as the demo shows it.

    The same fields `ReceiptOut` gives an applicant, and for the same reason: no
    score, no rank and no weight. A demo that showed a percentage would be teaching
    a number this system will not defend.
    """

    label: str
    must_have: bool
    verdict: Verdict
    evidence: list[EvidenceRef] = Field(default_factory=list)


class DemoOut(BaseModel):
    posting_title: str
    filename: str
    mode: DemoMode
    document_text: str
    """The text every offset indexes into, so the page highlights rather than
    searches — the same contract `ReceiptOut` carries."""

    requirements: list[DemoRequirementOut]
    dropped: list[DroppedClaim] = Field(default_factory=list)
    verified: int
    """Quotes that were located in the document."""

    dropped_count: int
    """Quotes that were not, and were therefore refused. Named separately from the
    list because a count of zero is a result worth stating, and an empty list on a
    page reads as a section that failed to load."""


@router.get("/screening", response_model=DemoOut)
async def run_demo(mode: DemoMode = DemoMode.FAITHFUL) -> DemoOut:
    """Judge the demo document and report what survived.

    An unknown `mode` is a 422 from the enum rather than a silent fallback to
    faithful: a visitor who asked to see the fabricating model and was shown the
    honest one would come away with the opposite of the point.
    """
    extractor = FakeExtractor(
        FakeMode.HALLUCINATING if mode is DemoMode.FABRICATING else FakeMode.FAITHFUL
    )
    # `from_stored` with no page spans: the demo text is one page, and this is the
    # same constructor the screening path uses to rebuild a document from a row
    # rather than a second way of making one.
    document = ParsedDocument.from_stored(DEMO_DOCUMENT_TEXT, None)

    outcome = await judge_requirements(document, DEMO_REQUIREMENTS, extractor, max_attempts=1)
    judgment = outcome.judgment

    return DemoOut(
        posting_title=DEMO_POSTING_TITLE,
        filename=DEMO_FILENAME,
        mode=mode,
        document_text=document.text,
        requirements=[
            DemoRequirementOut(
                label=item.label,
                must_have=item.must_have,
                verdict=item.verdict,
                evidence=item.evidence,
            )
            for item in judgment.requirements
        ],
        dropped=judgment.dropped,
        verified=judgment.stats.verified,
        dropped_count=judgment.stats.dropped,
    )
