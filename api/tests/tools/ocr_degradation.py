"""Measure where OCR stops working, and what confidence says while it happens.

Run against a real Tesseract — it is a measurement tool, not a test:

    python tests/tools/ocr_degradation.py --tesseract C:\\Users\\golfv\\tesseract.exe

This exists because of one finding: **a badly degraded scan does not fail, it
succeeds with nonsense.** At 6px blur `resume_scanned.pdf` still yields far more
than `MIN_CHARS_PER_TEXT_PAGE` characters, so the page is accepted as readable —
but "Somchai Jaidee" has become "Sore hector". A character count cannot tell text
from noise. Tesseract's per-word confidence can, and this script is how the
threshold in `OCR_MIN_CONFIDENCE` was chosen rather than guessed.

For each degradation it reports two numbers side by side:

*   **lines found** — how many of the known lines of the fixture survive well enough
    to be located in the recognized text. This is the ground truth: it is the same
    question `evidence.py` asks of a quote.
*   **mean confidence** — what Tesseract reports about its own reading, which is the
    only signal available at runtime, when the truth is not known.

A useful threshold is one that separates them: high confidence wherever lines are
still found, low wherever they are not. The measured table lives in
`docs/HANDOFF.md` §7.
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pdfplumber
from PIL import Image, ImageEnhance, ImageFilter

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "resume_scanned.pdf"

# What the fixture says. Recognizing these is what "working" means.
KNOWN_LINES = [
    "Somchai Jaidee",
    "Senior Backend Engineer",
    "Acme Logistics",
    "Built payment reconciliation services in Python.",
    "Python, FastAPI, PostgreSQL",
]

Degradation = tuple[str, Callable[[Image.Image], Image.Image]]


def _rotate(degrees: float) -> Callable[[Image.Image], Image.Image]:
    return lambda image: image.rotate(degrees, expand=True, fillcolor="white")


def _blur(radius: float) -> Callable[[Image.Image], Image.Image]:
    return lambda image: image.filter(ImageFilter.GaussianBlur(radius))


def _scale(factor: float) -> Callable[[Image.Image], Image.Image]:
    def apply(image: Image.Image) -> Image.Image:
        size = (max(1, int(image.width * factor)), max(1, int(image.height * factor)))
        return image.resize(size, Image.Resampling.LANCZOS)

    return apply


def _contrast(factor: float) -> Callable[[Image.Image], Image.Image]:
    return lambda image: ImageEnhance.Contrast(image).enhance(factor)


def _jpeg(quality: int) -> Callable[[Image.Image], Image.Image]:
    def apply(image: Image.Image) -> Image.Image:
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=quality)
        buffer.seek(0)
        return Image.open(buffer)

    return apply


DEGRADATIONS: list[Degradation] = [
    ("clean", lambda image: image),
    *[(f"rotate {d}deg", _rotate(d)) for d in (2, 5, 8, 12)],
    *[(f"blur {r}px", _blur(r)) for r in (1.5, 3.0, 4.5, 6.0)],
    *[(f"scale 1/{int(1 / f)}", _scale(f)) for f in (0.5, 0.25, 1 / 6, 0.125)],
    ("contrast 0.4", _contrast(0.4)),
    ("jpeg q3", _jpeg(3)),
]


def _run(command: str, image: Image.Image, languages: str, *extra: str) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    completed = subprocess.run(
        [command, "stdin", "stdout", "-l", languages, *extra],
        input=buffer.getvalue(),
        capture_output=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")


def mean_confidence(tsv: str) -> float:
    """The same statistic `TesseractEngine` computes at runtime."""
    scores = []
    for line in tsv.splitlines()[1:]:
        columns = line.split("\t")
        if len(columns) >= 12 and columns[11].strip():
            try:
                score = float(columns[10])
            except ValueError:
                continue
            if score >= 0:
                scores.append(score)
    return sum(scores) / len(scores) if scores else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tesseract", required=True, help="path to the tesseract binary")
    parser.add_argument("--languages", default="tha+eng")
    arguments = parser.parse_args()

    with pdfplumber.open(FIXTURE) as pdf:
        original = pdf.pages[0].to_image(resolution=300).original

    print(f"{'degradation':<16} {'lines found':>12} {'chars':>7} {'mean conf':>10}")
    print("-" * 48)
    for name, degrade in DEGRADATIONS:
        image = degrade(original)
        text = _run(arguments.tesseract, image, arguments.languages)
        tsv = _run(arguments.tesseract, image, arguments.languages, "tsv")
        found = sum(1 for line in KNOWN_LINES if line in text)
        print(
            f"{name:<16} {f'{found}/{len(KNOWN_LINES)}':>12} "
            f"{len(text.strip()):>7} {mean_confidence(tsv):>10.1f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
