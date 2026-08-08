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

import pdfplumber
import pytest
from PIL import ImageFilter
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.config import OCREngineName, Settings
from app.pipeline.evidence import EvidenceResolver, ResolvedSpan
from app.pipeline.ocr import _mean_confidence, build_ocr_engine
from app.pipeline.parse import NoTextLayerError, parse_pdf
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

    def test_line_endings_are_normalized(self, scanned):
        """Tesseract emits CRLF on Windows and LF elsewhere. Unnormalized, the same
        scan would yield different offsets per platform, and a part-scanned document
        would carry both conventions in one `document_text`."""
        assert "\r" not in scanned.text

    def test_quotes_resolve_against_the_recognized_text(self, scanned):
        """The guardrail end to end: the model quotes what OCR produced, and the
        resolver finds it in exactly that string."""
        resolver = EvidenceResolver(scanned.text)
        for quote in ("Somchai Jaidee", "Built payment reconciliation services in Python."):
            assert isinstance(resolver.resolve(quote), ResolvedSpan), quote


class TestTheConfidenceGateAgainstTheRealBinary:
    """The gate stops being useful the moment the numbers stop being real.

    `test_ocr.py` pins the logic against a stubbed subprocess. What it cannot show
    is what Tesseract actually reports — whether a clean page really scores above
    the threshold and a ruined one really scores below it. That is the measurement
    the default `OCR_MIN_CONFIDENCE` rests on, so it is pinned here where a real
    binary exists. Full table: `tests/tools/ocr_degradation.py`.
    """

    def _engine(self, min_confidence: float):
        return build_ocr_engine(
            Settings(
                _env_file=None,
                ocr_engine=OCREngineName.TESSERACT,
                ocr_command=OCR_TESSERACT_CMD,
                ocr_min_confidence=min_confidence,
            )
        )

    def _page_image(self, name: str):
        with pdfplumber.open(FIXTURES / name) as pdf:
            return pdf.pages[0].to_image(resolution=300).original

    def test_a_clean_scan_scores_well_above_the_default(self):
        engine = self._engine(0)
        image = self._page_image("resume_scanned.pdf")
        tsv = engine._run(engine._encode(image), 1, "tsv")
        assert _mean_confidence(tsv) > 90, "the measured clean baseline is ~94.8"

    def test_a_ruined_scan_scores_far_below_it(self):
        """6px of blur: the page still yields plenty of characters, but "Somchai
        Jaidee" comes back as "Sore hector". This is the case the gate exists for."""
        engine = self._engine(0)
        blurred = self._page_image("resume_scanned.pdf").filter(ImageFilter.GaussianBlur(6.0))
        tsv = engine._run(engine._encode(blurred), 1, "tsv")
        assert _mean_confidence(tsv) < 60, "the measured 6px-blur reading is ~47.4"

    def test_the_default_threshold_keeps_a_clean_scan(self):
        document = parse_pdf(FIXTURES / "resume_scanned.pdf", ocr=self._engine(75))
        assert document.pages_from_ocr == (1,)
        assert "ทักษะ" in document.text

    def test_the_default_threshold_refuses_a_ruined_one(self, tmp_path):
        """End to end, with a real Tesseract: a blurred scan comes back as a failure
        the user can act on rather than a confident profile of the wrong words."""
        blurred = self._page_image("resume_scanned.pdf").filter(ImageFilter.GaussianBlur(6.0))
        path = tmp_path / "blurred.pdf"
        canvas_ = canvas.Canvas(str(path), pagesize=A4)
        canvas_.drawImage(ImageReader(blurred), 0, 0, width=A4[0], height=A4[1])
        canvas_.save()

        with pytest.raises(NoTextLayerError) as caught:
            parse_pdf(path, ocr=self._engine(75))
        assert caught.value.ocr_attempted is True

        # ...and with the gate off, the same file is accepted — which is the whole
        # problem, stated as a test rather than as a caveat.
        accepted = parse_pdf(path, ocr=self._engine(0))
        assert accepted.pages_from_ocr == (1,)
        assert "Somchai Jaidee" not in accepted.text


class TestARealPartialScan:
    def test_only_the_scanned_page_goes_through_ocr(self, engine):
        doc = parse_pdf(FIXTURES / "resume_mixed_scan.pdf", ocr=engine)
        assert doc.pages_from_ocr == (2,)
        # Page 1's text layer is untouched, page 2 comes from the image.
        assert "Preecha Boonmee" in doc.text
        assert "Riverbank Analytics" in doc.text

    def test_both_halves_share_one_line_ending_convention(self, engine):
        """The document most likely to mix them, since its two pages come from
        different readers."""
        doc = parse_pdf(FIXTURES / "resume_mixed_scan.pdf", ocr=engine)
        assert "\r" not in doc.text
