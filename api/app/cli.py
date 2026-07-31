"""Run the extraction pipeline from the terminal.

    python -m app.cli path/to/resume.pdf
    python -m app.cli path/to/resume.pdf --provider gemini

Exists for three reasons: it proves the pipeline end-to-end without the web stack,
it is the fastest way to eyeball a new document's output while tuning prompts, and
it prints the verification counters that M6's metrics will aggregate.
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
from app.pipeline.parse import ParseError, parse_document
from app.schemas.profile import EvidenceRef


def _cite(reference: EvidenceRef) -> str:
    quote = " ".join(reference.quote.split())
    if len(quote) > 60:
        quote = quote[:57] + "..."
    flag = " [AMBIGUOUS]" if reference.is_ambiguous else ""
    return f'p{reference.page} {reference.char_start}-{reference.char_end} "{quote}"{flag}'


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

    stats = profile.stats
    cost = "unknown" if outcome.total_cost_usd is None else f"${outcome.total_cost_usd:.6f}"
    print(
        f"\nverified {stats.verified}/{stats.total_claims}"
        f"  hallucination_rate {stats.hallucination_rate:.2%}"
        f"  attempts {stats.attempts}"
        f"  {outcome.total_latency_ms}ms"
        f"  cost {cost}"
    )
    if stats.by_match_kind:
        kinds = ", ".join(f"{kind}={count}" for kind, count in stats.by_match_kind.items())
        print(f"match kinds: {kinds}")


async def _run(paths: list[Path], provider: LLMProvider | None) -> int:
    settings = get_settings()
    if provider is not None:
        settings = settings.model_copy(update={"llm_provider": provider})

    try:
        extractor = build_extractor(settings)
    except LLMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"provider: {extractor.provider_name}")
    exit_code = 0
    try:
        for path in paths:
            try:
                document = parse_document(path)
            except ParseError as exc:
                print(f"\n=== {path.name} ===\nparse failed: {exc}", file=sys.stderr)
                exit_code = 1
                continue

            if document.pages_without_text:
                print(
                    f"note: {path.name} has no text on page(s) "
                    f"{', '.join(map(str, document.pages_without_text))} — needs OCR (M2)",
                    file=sys.stderr,
                )

            try:
                outcome = await extract_profile(
                    document, extractor, max_attempts=settings.extraction_max_attempts
                )
            except LLMError as exc:
                print(f"\n=== {path.name} ===\nextraction failed: {exc}", file=sys.stderr)
                exit_code = 1
                continue

            _print_report(outcome, source=path)
    finally:
        await extractor.aclose()

    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract a verified profile from a resume.")
    parser.add_argument("paths", nargs="+", type=Path, help="Resume file(s) to process.")
    parser.add_argument(
        "--provider",
        type=LLMProvider,
        choices=list(LLMProvider),
        default=None,
        help="Override LLM_PROVIDER for this run.",
    )
    args = parser.parse_args(argv)
    return asyncio.run(_run(args.paths, args.provider))


if __name__ == "__main__":
    sys.exit(main())
