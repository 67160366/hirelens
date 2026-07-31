"""A fixture-free fake extractor: real rule-based extraction over the real document.

The important property is that every quote it emits is copied out of the document
it was given. That makes it useful for far more than stubbing a return value —
the whole pipeline, evidence validation included, runs truthfully against any
document with no API key and no spend. Tests assert on real behaviour instead of
on a canned blob.

It is deliberately dumb: sections by heading, roles by regex. It exists to exercise
the plumbing, not to compete with a model. `FakeMode` lets a test ask for the
failure shapes that matter — a fabricated quote, or an unreachable backend.
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

        if schema is not RawExtraction:
            raise LLMResponseError(
                f"{type(self).__name__} only produces RawExtraction, not {schema.__name__}"
            )

        started = time.perf_counter()
        extraction = self._extract_from(_document_from_prompt(user))
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
        return StructuredResult(value=extraction, usage=usage, raw_text="")  # type: ignore[arg-type]

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
