"""The real Tesseract, which the rest of the suite never runs.

`test_ocr.py` drives the OCR path through a stub, which pins the wiring, the
offset contract and the failure classification — but proves nothing about whether
Tesseract is actually invoked correctly, or whether Thai survives the round trip.
That is what this module is for, and it is skipped unless `OCR_TESSERACT_CMD`
points at a binary, so `pytest -q` and CI stay free of a system dependency:

    OCR_TESSERACT_CMD="C:\\Users\\golfv\\tesseract.exe" pytest tests/test_ocr_tesseract.py -q

The binary needs `tha` and `eng` traineddata. `build_ocr_engine` refuses to build
without them, which is the failure this module would otherwise hide: English would
keep working and Thai would come back as noise.
"""

from __future__ import annotations

import os

import pytest

from app.config import OCREngineName, Settings
from app.pipeline.evidence import EvidenceResolver, ResolvedSpan
from app.pipeline.ocr import build_ocr_engine
from app.pipeline.parse import parse_pdf
from tests.conftest import FIXTURES

OCR_TESSERACT_CMD = os.environ.get("OCR_TESSERACT_CMD", "")

pytestmark = pytest.mark.skipif(
    not OCR_TESSERACT_CMD,
    reason="Set OCR_TESSERACT_CMD to a Tesseract binary (with tha+eng) to run these.",
)


@pytest.fixture(scope="module")
def engine():
    """A real engine, built the way the application builds one.

    Going through `build_ocr_engine` rather than constructing `TesseractEngine`
    directly means the startup probe — including the language-pack check — is part
    of what this module verifies.
    """
    return build_ocr_engine(
        Settings(
            _env_file=None,
            ocr_engine=OCREngineName.TESSERACT,
            ocr_command=OCR_TESSERACT_CMD,
        )
    )


@pytest.fixture(scope="module")
def scanned(engine):
    return parse_pdf(FIXTURES / "resume_scanned.pdf", ocr=engine)


class TestARealScan:
    def test_the_page_is_recovered(self, scanned):
        assert scanned.pages_from_ocr == (1,)
        assert scanned.pages_without_text == ()

    def test_latin_text_is_recognized(self, scanned):
        assert "Somchai Jaidee" in scanned.text
        assert "Acme Logistics" in scanned.text

    def test_thai_survives_recognition(self, scanned):
        """The reason `tha` is refused as optional: without it this is noise."""
        assert "ทักษะ" in scanned.text

    def test_recognized_text_carries_no_nul(self, scanned):
        """Postgres refuses NUL in a text column, and OCR output reaches the same
        `_assemble` that strips it — see HANDOFF §11."""
        assert "\x00" not in scanned.text

    def test_quotes_resolve_against_the_recognized_text(self, scanned):
        """The guardrail end to end: the model quotes what OCR produced, and the
        resolver finds it in exactly that string."""
        resolver = EvidenceResolver(scanned.text)
        for quote in ("Somchai Jaidee", "Built payment reconciliation services in Python."):
            assert isinstance(resolver.resolve(quote), ResolvedSpan), quote


class TestARealPartialScan:
    def test_only_the_scanned_page_goes_through_ocr(self, engine):
        doc = parse_pdf(FIXTURES / "resume_mixed_scan.pdf", ocr=engine)
        assert doc.pages_from_ocr == (2,)
        # Page 1's text layer is untouched, page 2 comes from the image.
        assert "Preecha Boonmee" in doc.text
        assert "Riverbank Analytics" in doc.text
