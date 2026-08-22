"""Show what a plain text extractor does to a two-column resume, and what this does.

    api/.venv/Scripts/python.exe docs/pitch/sample/compare_parse.py

Both halves read the same file. The left is `pdfplumber.Page.extract_text()`, the
call a straightforward parser makes; the right is `app.pipeline.parse`, which cuts
the page into horizontal bands, then into columns, and lets pdfplumber assemble each
region on its own (`app/pipeline/layout.py`).

The point of printing them side by side is that the difference is not an opinion:
in the naive output a skill from the sidebar and a sentence from the work history
end up on **one line**, so any downstream matcher is reading a sentence the document
does not contain.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "api"))

import pdfplumber  # noqa: E402

from app.pipeline.parse import parse_document  # noqa: E402

SAMPLE = Path(__file__).parent / "sample_resume_th.pdf"
LINES = 14


def naive(path: Path) -> list[str]:
    with pdfplumber.open(path) as pdf:
        return (pdf.pages[0].extract_text() or "").splitlines()


def ours(path: Path) -> list[str]:
    return parse_document(path).text.splitlines()


def main() -> int:
    if not SAMPLE.exists():
        raise SystemExit(f"missing {SAMPLE} — run generate_sample.py first")

    left, right = naive(SAMPLE), ours(SAMPLE)

    print(f"file: {SAMPLE.name}   ({SAMPLE.stat().st_size:,} bytes, A4, one page)")
    print()
    print("=" * 78)
    print("A plain text extractor  —  pdfplumber.Page.extract_text()")
    print("=" * 78)
    for line in left[:LINES]:
        print("  " + line)
    print(f"  … ({len(left)} lines total)")
    print()
    print("=" * 78)
    print("This pipeline  —  app.pipeline.parse, layout-aware")
    print("=" * 78)
    for line in right[:LINES]:
        print("  " + line)
    print(f"  … ({len(right)} lines total)")
    print()

    # The measurable claim: lines that fuse the sidebar into the work history.
    sidebar = {"Python, FastAPI", "PostgreSQL, Redis", "Celery, RabbitMQ", "pytest, Grafana"}
    fused = [
        line
        for line in left
        if any(line.startswith(item) and line.strip() != item for item in sidebar)
    ]
    print(f"lines in the naive output that fuse two columns into one: {len(fused)}")
    for line in fused:
        print(f"  ! {line}")
    print()
    print("the same lines after layout detection:")
    for item in sorted(sidebar):
        print(f"  ✓ {item}" if item in right else f"  ? {item} (not found on its own line)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
