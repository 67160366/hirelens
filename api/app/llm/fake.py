"""A fixture-free fake backend: real rule-based work over the real document.

The important property is that every quote it emits is copied out of the document
it was given. That makes it useful for far more than stubbing a return value —
the whole pipeline, evidence validation included, runs truthfully against any
document with no API key and no spend. Tests assert on real behaviour instead of
on a canned blob.

It answers both of the schemas this system asks for: `RawExtraction` (a profile)
and `RawJudgment` (which of a job's requirements the resume evidences). Judging had
to be taught here rather than mocked per test, because `git clone && pytest -q`
working with no servers and no API key is load-bearing — see `docs/HANDOFF.md` §2.

It is deliberately dumb: sections by heading, roles by regex, requirements by
substring. It exists to exercise the plumbing, not to compete with a model.
`FakeMode` lets a test ask for the failure shapes that matter — a fabricated quote,
or an unreachable backend.
"""

from __future__ import annotations

import re
import time
from enum import StrEnum
from typing import ClassVar

from app.llm.base import (
    LLMResponseError,
    LLMUnavailableError,
    LLMUsage,
    SchemaT,
    StructuredExtractor,
    StructuredResult,
)
from app.schemas.extraction import (
    RawClaim,
    RawEducation,
    RawExperience,
    RawExtraction,
    RawSkill,
    Seniority,
)
from app.schemas.judgment import RawJudgment, RawRequirementMatch


class FakeMode(StrEnum):
    FAITHFUL = "faithful"
    """Every quote is copied from the document. The default."""

    HALLUCINATING = "hallucinating"
    """Adds one claim whose quote is not in the document, to exercise rejection."""

    UNAVAILABLE = "unavailable"
    """Raises, to exercise the backend-down path."""


# Section headings, English and Thai. Matched case-insensitively against a whole line.
_HEADINGS: dict[str, str] = {
    "experience": "experience",
    "work experience": "experience",
    "ประสบการณ์ทำงาน": "experience",
    "ประสบการณ์": "experience",
    "skills": "skills",
    "ทักษะ": "skills",
    "education": "education",
    "การศึกษา": "education",
    "summary": "summary",
    "contact": "contact",
}

# "Acme Logistics — Backend Engineer (Jan 2021 - Mar 2024)" and the Thai equivalent.
_ROLE_LINE = re.compile(
    r"^(?P<company>.+?)\s*[—–-]\s*(?P<title>.+?)\s*"
    r"\((?P<start>[^)\-–—]+?)\s*[-–—]\s*(?P<end>[^)]+?)\)\s*$"
)

# "Chulalongkorn University — B.Eng Computer Engineering (2015 - 2019)"
_EDUCATION_LINE = re.compile(r"^(?P<institution>.+?)\s*[—–-]\s*(?P<credential>.+?)\s*(?:\(.*\))?$")

_SENIORITY_HINTS: tuple[tuple[Seniority, tuple[str, ...]], ...] = (
    (Seniority.LEAD, ("lead", "principal", "head of", "หัวหน้า")),
    (Seniority.SENIOR, ("senior", "sr.", "อาวุโส")),
    (Seniority.JUNIOR, ("junior", "jr.", "intern", "ฝึกงาน")),
)

_FABRICATED_QUOTE = "Led a team of 12 engineers at a company never named in this document"

# The pipeline wraps the document in a prompt. A real model reads past the
# instructions to find the document; the fake has to do the same, or it extracts
# the prompt's own wording and every quote fails verification.
_RESUME_BLOCK = re.compile(r"<resume>\s*(?P<document>.*?)\s*</resume>", re.DOTALL)


def _document_from_prompt(user: str) -> str:
    """Pull the document out of a prompt, or treat the input as the document.

    Accepting bare text keeps the fake usable directly in tests that do not build
    a prompt first.
    """
    match = _RESUME_BLOCK.search(user)
    return match.group("document") if match else user


# "3. [skill] PostgreSQL" — the numbering `build_judgment_user_prompt` writes and
# `RawRequirementMatch.requirement` refers back to.
_REQUIREMENT_LINE = re.compile(r"^\s*(?P<number>\d+)\.\s*\[[^\]]*\]\s*(?P<label>.+?)\s*$")


def _requirements_from_prompt(user: str) -> list[tuple[int, str]]:
    """Read the numbered requirement list back out of a judging prompt.

    Only the part *before* `<resume>` is scanned. A real resume can easily contain
    a line that looks like "1. [something] ...", and treating one as a requirement
    would have the fake answer about the document's own bullet points.
    """
    head = user.split("<resume>", 1)[0]
    return [
        (int(match.group("number")), match.group("label"))
        for line in head.splitlines()
        if (match := _REQUIREMENT_LINE.match(line)) is not None
    ]


def _classify_heading(line: str) -> str | None:
    return _HEADINGS.get(line.strip().casefold())


def _sectionize(text: str) -> dict[str, list[str]]:
    """Group non-empty lines under the heading that precedes them."""
    sections: dict[str, list[str]] = {"_preamble": []}
    current = "_preamble"

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        heading = _classify_heading(line)
        if heading is not None:
            current = heading
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)

    return sections


def _split_skills(lines: list[str]) -> list[str]:
    skills: list[str] = []
    for line in lines:
        for part in re.split(r"[,;/·|]", line):
            skill = part.strip()
            if skill:
                skills.append(skill)
    return skills


def _detect_seniority(headline: str) -> Seniority:
    lowered = headline.casefold()
    for level, hints in _SENIORITY_HINTS:
        if any(hint in lowered for hint in hints):
            return level
    return Seniority.UNKNOWN


class FakeExtractor(StructuredExtractor):
    provider_name: ClassVar[str] = "fake"

    def __init__(self, mode: FakeMode = FakeMode.FAITHFUL) -> None:
        self.mode = mode
        self.call_count = 0

    async def extract(
        self,
        *,
        system: str,
        user: str,
        schema: type[SchemaT],
    ) -> StructuredResult[SchemaT]:
        self.call_count += 1

        if self.mode is FakeMode.UNAVAILABLE:
            raise LLMUnavailableError("fake backend is configured as unavailable")

        if schema is not RawExtraction and schema is not RawJudgment:
            raise LLMResponseError(
                f"{type(self).__name__} produces RawExtraction or RawJudgment, "
                f"not {schema.__name__}"
            )

        started = time.perf_counter()
        document = _document_from_prompt(user)
        value: RawExtraction | RawJudgment = (
            self._extract_from(document)
            if schema is RawExtraction
            else self._judge(document, _requirements_from_prompt(user))
        )
        latency_ms = int((time.perf_counter() - started) * 1000)

        usage = LLMUsage(
            provider=self.provider_name,
            model=f"rule-based-{self.mode}",
            input_tokens=len(user) // 4,
            output_tokens=0,
            latency_ms=latency_ms,
            cost_usd=0.0,
        )
        # The schema check above guarantees the cast is sound.
        return StructuredResult(value=value, usage=usage, raw_text="")  # type: ignore[arg-type]

    def _extract_from(self, document: str) -> RawExtraction:
        sections = _sectionize(document)
        preamble = sections.get("_preamble", [])

        full_name = RawClaim(value=preamble[0], quote=preamble[0]) if len(preamble) >= 1 else None
        headline = RawClaim(value=preamble[1], quote=preamble[1]) if len(preamble) >= 2 else None

        seniority = Seniority.UNKNOWN
        seniority_quote = ""
        if headline is not None:
            seniority = _detect_seniority(headline.value)
            if seniority is not Seniority.UNKNOWN:
                seniority_quote = headline.value

        skills = [
            RawSkill(name=name, quote=name) for name in _split_skills(sections.get("skills", []))
        ]

        experiences: list[RawExperience] = []
        for line in sections.get("experience", []):
            match = _ROLE_LINE.match(line)
            if match is None:
                continue
            experiences.append(
                RawExperience(
                    company=match.group("company").strip(),
                    title=match.group("title").strip(),
                    start=match.group("start").strip(),
                    end=match.group("end").strip(),
                    quote=line,
                )
            )

        education: list[RawEducation] = []
        for line in sections.get("education", []):
            match = _EDUCATION_LINE.match(line)
            if match is None:
                continue
            education.append(
                RawEducation(
                    institution=match.group("institution").strip(),
                    credential=match.group("credential").strip(),
                    quote=line,
                )
            )

        if self.mode is FakeMode.HALLUCINATING:
            # A claim whose quote is nowhere in the document. The evidence resolver
            # must drop this and count it.
            skills.append(RawSkill(name="Team leadership", quote=_FABRICATED_QUOTE))

        return RawExtraction(
            full_name=full_name,
            headline=headline,
            seniority=seniority,
            seniority_quote=seniority_quote,
            skills=skills,
            experiences=experiences,
            education=education,
        )

    def _judge(self, document: str, requirements: list[tuple[int, str]]) -> RawJudgment:
        """Report the requirements whose label appears in the document.

        **Quotes the whole line the label sits on, not the label.** A label like
        "Go" is under `MIN_QUOTE_CHARS` and would be rejected as too short before it
        ever reached a verdict; a line is real evidence, and it is still copied
        character-for-character out of the document, which is the property that
        makes this worth more than a canned response.

        A requirement whose label is nowhere in the document is simply left out —
        that omission is what the pipeline turns into `not_evidenced`. One quote per
        requirement, deliberately: a test that needs a specific shape (several
        quotes, a duplicate number, an unknown number) scripts it directly, the way
        `tests/test_extract.py` scripts extractions the rule-based path cannot pose.
        """
        lines = [line.strip() for line in document.splitlines()]
        matches: list[RawRequirementMatch] = []

        for number, label in requirements:
            needle = label.casefold()
            quote = next((line for line in lines if line and needle in line.casefold()), None)
            if quote is not None:
                matches.append(RawRequirementMatch(requirement=number, quotes=[quote]))

        if self.mode is FakeMode.HALLUCINATING and requirements:
            # Attach the fabrication to a requirement the document does *not*
            # evidence, wherever one exists. That is the sharper test: a made-up
            # quote must not be able to manufacture a `met` verdict, and here it
            # has nothing real beside it to hide behind.
            evidenced = {match.requirement for match in matches}
            target = next(
                (number for number, _ in requirements if number not in evidenced),
                requirements[-1][0],
            )
            for match in matches:
                if match.requirement == target:
                    match.quotes.append(_FABRICATED_QUOTE)
                    break
            else:
                matches.append(RawRequirementMatch(requirement=target, quotes=[_FABRICATED_QUOTE]))

        return RawJudgment(matches=matches)
