"""Run the extraction or judging pipeline from the terminal.

    python -m app.cli path/to/resume.pdf
    python -m app.cli path/to/resume.pdf --provider gemini
    python -m app.cli path/to/resume.pdf --requirement skill:Python

Exists for three reasons: it proves the pipeline end-to-end without the web stack,
it is the fastest way to eyeball a new document's output while tuning prompts, and
it prints the verification counters that M6's metrics will aggregate.

`--requirement` is a flag rather than a subcommand on purpose. The bare form above
is named in `CLAUDE.md` as this project's fastest sanity check, and moving it under
a subcommand would break the one command everybody already types. With no
`--requirement` the run is exactly what it was — the same "the old path stays the
old path" rule that made column detection safe to ship.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.config import LLMProvider, get_settings
from app.llm.base import LLMError
from app.llm.registry import build_extractor
from app.pipeline.extract import ExtractionOutcome, extract_profile
from app.pipeline.judge import JudgmentOutcome, judge_requirements
from app.pipeline.ocr import OCRError, build_ocr_engine
from app.pipeline.parse import ParseError, parse_document
from app.schemas.judgment import RequirementSpec, Verdict
from app.schemas.profile import EvidenceRef, EvidenceStats


def _cite(reference: EvidenceRef) -> str:
    quote = " ".join(reference.quote.split())
    if len(quote) > 60:
        quote = quote[:57] + "..."
    flag = " [AMBIGUOUS]" if reference.is_ambiguous else ""
    return f'p{reference.page} {reference.char_start}-{reference.char_end} "{quote}"{flag}'


def _parse_requirement(index: int, raw: str) -> RequirementSpec:
    """Read one `kind:label` argument, or a bare `label` for kind `other`.

    Split on the *first* colon, so `experience:3+ years backend` works and a label
    that itself contains a colon keeps everything after the first one.
    """
    kind, separator, label = raw.partition(":")
    if not separator:
        kind, label = "other", raw

    label = label.strip()
    if not label:
        raise ValueError(f"requirement {raw!r} has no label")

    return RequirementSpec(id=f"cli-{index}", label=label, kind=kind.strip().casefold() or "other")


def _print_stats(
    stats: EvidenceStats, *, cost_usd: float | None, latency_ms: int, prefix: str = ""
) -> None:
    cost = "unknown" if cost_usd is None else f"${cost_usd:.6f}"
    print(
        f"\n{prefix}verified {stats.verified}/{stats.total_claims}"
        f"  hallucination_rate {stats.hallucination_rate:.2%}"
        f"  attempts {stats.attempts}"
        f"  {latency_ms}ms"
        f"  cost {cost}"
    )
    if stats.by_match_kind:
        kinds = ", ".join(f"{kind}={count}" for kind, count in stats.by_match_kind.items())
        print(f"match kinds: {kinds}")


def _print_judgment_report(outcome: JudgmentOutcome, *, source: Path) -> None:
    judgment = outcome.judgment
    print(f"\n=== {source.name} ===")

    for item in judgment.requirements:
        # "NOT EVIDENCED", never "not met": the system cannot tell a candidate who
        # lacks something from a resume that does not mention it.
        mark = "MET" if item.verdict is Verdict.MET else "NOT EVIDENCED"
        gate = "  (must have)" if item.must_have else ""
        print(f"[{mark:^13}] {item.label}{gate}")
        for reference in item.evidence:
            print(f"{'':15}↳ {_cite(reference)}")

    if judgment.dropped:
        print(f"\nDropped — quote not found in the document ({len(judgment.dropped)})")
        for dropped in judgment.dropped:
            print(f"  ! {dropped.field}: {dropped.value!r} [{dropped.reason}]")
            print(f"      claimed quote: {dropped.quote!r}")

    _print_stats(
        judgment.stats,
        cost_usd=outcome.total_cost_usd,
        latency_ms=outcome.total_latency_ms,
        prefix=f"met {judgment.met_count}/{len(judgment.requirements)}  ",
    )


def _print_report(outcome: ExtractionOutcome, *, source: Path) -> None:
    profile = outcome.profile
    print(f"\n=== {source.name} ===")

    for label, claim in (
        ("Name", profile.full_name),
        ("Headline", profile.headline),
        ("Years", profile.years_experience),
    ):
        if claim is not None:
            print(f"{label:10} {claim.value}")
            print(f"{'':10}   ↳ {_cite(claim.evidence)}")

    print(f"{'Seniority':10} {profile.seniority}")
    if profile.seniority_evidence is not None:
        print(f"{'':10}   ↳ {_cite(profile.seniority_evidence)}")

    if profile.skills:
        print(f"\nSkills ({len(profile.skills)})")
        for skill in profile.skills:
            print(f"  - {skill.value:24} ↳ {_cite(skill.evidence)}")

    if profile.experiences:
        print(f"\nExperience ({len(profile.experiences)})")
        for role in profile.experiences:
            print(f"  - {role.title} @ {role.company} ({role.start} – {role.end})")
            print(f"      ↳ {_cite(role.evidence)}")

    if profile.education:
        print(f"\nEducation ({len(profile.education)})")
        for entry in profile.education:
            print(f"  - {entry.credential}, {entry.institution}")
            print(f"      ↳ {_cite(entry.evidence)}")

    if profile.dropped:
        print(f"\nDropped — quote not found in the document ({len(profile.dropped)})")
        for dropped in profile.dropped:
            print(f"  ! {dropped.field}: {dropped.value!r} [{dropped.reason}]")
            print(f"      claimed quote: {dropped.quote!r}")

    _print_stats(
        profile.stats, cost_usd=outcome.total_cost_usd, latency_ms=outcome.total_latency_ms
    )


async def _run(
    paths: list[Path],
    provider: LLMProvider | None,
    requirements: list[RequirementSpec],
) -> int:
    settings = get_settings()
    if provider is not None:
        settings = settings.model_copy(update={"llm_provider": provider})

    try:
        extractor = build_extractor(settings)
    except LLMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        ocr = build_ocr_engine(settings)
    except OCRError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"provider: {extractor.provider_name}  ocr: {settings.ocr_engine}")
    exit_code = 0
    try:
        for path in paths:
            try:
                document = parse_document(path, ocr=ocr)
            except (ParseError, OCRError) as exc:
                print(f"\n=== {path.name} ===\nparse failed: {exc}", file=sys.stderr)
                exit_code = 1
                continue

            if document.pages_from_ocr:
                print(
                    f"note: {path.name} page(s) "
                    f"{', '.join(map(str, document.pages_from_ocr))} were read by OCR — "
                    "quoted text from them may contain recognition errors",
                    file=sys.stderr,
                )
            if document.pages_without_text:
                print(
                    f"note: {path.name} has no text on page(s) "
                    f"{', '.join(map(str, document.pages_without_text))} — "
                    "nothing there can be cited",
                    file=sys.stderr,
                )

            try:
                if requirements:
                    judgment = await judge_requirements(
                        document,
                        requirements,
                        extractor,
                        max_attempts=settings.judgment_max_attempts,
                    )
                else:
                    outcome = await extract_profile(
                        document, extractor, max_attempts=settings.extraction_max_attempts
                    )
            except LLMError as exc:
                what = "judging" if requirements else "extraction"
                print(f"\n=== {path.name} ===\n{what} failed: {exc}", file=sys.stderr)
                exit_code = 1
                continue

            if requirements:
                _print_judgment_report(judgment, source=path)
            else:
                _print_report(outcome, source=path)
    finally:
        await extractor.aclose()

    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract a verified profile from a resume, or judge it against requirements."
    )
    parser.add_argument("paths", nargs="+", type=Path, help="Resume file(s) to process.")
    parser.add_argument(
        "--provider",
        type=LLMProvider,
        choices=list(LLMProvider),
        default=None,
        help="Override LLM_PROVIDER for this run.",
    )
    parser.add_argument(
        "--requirement",
        action="append",
        default=[],
        metavar="KIND:LABEL",
        help=(
            "Judge the resume against this requirement instead of extracting a "
            "profile. Repeat for more. KIND is one of skill, experience, education, "
            "language, other; a bare LABEL means other."
        ),
    )
    args = parser.parse_args(argv)

    try:
        requirements = [
            _parse_requirement(index, raw) for index, raw in enumerate(args.requirement)
        ]
    except ValueError as exc:
        parser.error(str(exc))

    return asyncio.run(_run(args.paths, args.provider, requirements))


if __name__ == "__main__":
    sys.exit(main())
