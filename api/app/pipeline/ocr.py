"""Read text off a page that has no text layer.

A scanned resume is an image, so `pdfplumber` extracts nothing from it and the
document used to die at `NoTextLayerError`. This module turns those pages back
into text, which the parser then treats exactly like any other page.

Two properties are worth stating plainly, because they are what makes OCR safe to
add to a project built on citing verbatim text:

*   **OCR runs before offsets are measured.** `parse.py` substitutes the recognized
    text into the page list and only then measures page spans, so evidence offsets,
    page mapping and the document pane keep working untouched. It is the same
    reasoning as the NUL strip in `_assemble`: change the text before anything
    indexes into it, and nothing downstream shifts.
*   **The recognized text becomes `document_text`.** So a quote still has to be
    found in exactly what the model was shown — the guardrail is unchanged. What
    OCR cannot promise is that the text matches the *printed* page: a citation into
    an OCR'd page is faithful to what was read, which is not always what was
    printed. That limitation is surfaced to the user rather than hidden.

The engine is a seam with an off-by-default setting, for the same reason the fake
extractor is the default provider: Tesseract is a system binary, CI will never have
one, and `git clone && pytest -q` has to stay green with no servers. The suite
drives the whole path through a stub engine; real Tesseract is opt-in
(`tests/test_ocr_tesseract.py`).

`None` rather than a null-object engine means "OCR is off", so it never has to be
told apart from an engine that ran and found nothing — which is a real answer about
a page, not a configuration.
"""

from __future__ import annotations

import io
import logging
import subprocess
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

from app.config import OCREngineName, Settings

if TYPE_CHECKING:
    from PIL.Image import Image

# Resumes are PII: log page numbers, durations and character counts, never text.
logger = logging.getLogger(__name__)

# Long enough for a dense page at 300 dpi, short enough that a wedged binary does
# not hold a worker forever.
_PROBE_TIMEOUT_SECONDS = 30.0


class OCRError(Exception):
    """Base class for OCR failures."""


class OCRUnavailableError(OCRError):
    """The engine is selected but not usable.

    A missing binary or a missing language pack is a configuration fault, not a
    fact about the document — which is why it reads differently from
    `NoTextLayerError` and why fixing the config and retrying is worth doing.
    """


class OCREngine(ABC):
    """Turns one rendered page into text.

    `dpi` and `max_pages` live here rather than on the parser because they are OCR
    tuning, not parsing: the caller only has to hand over an engine.
    """

    engine_name: ClassVar[str]

    dpi: int = 300
    """Resolution the caller should rasterize at before calling `recognize`."""

    max_pages: int = 10
    """Most pages to spend OCR on in one document. A 60-page scan should not pin a
    worker for two minutes; the pages past the cap stay reported as text-less."""

    @abstractmethod
    def recognize(self, image: Image, *, page_number: int) -> str:
        """Return the text found in `image`, or an empty string if there is none.

        Raises:
            OCRUnavailableError: the engine stopped being usable.
            OCRError: the engine ran and failed.
        """


class TesseractEngine(OCREngine):
    """Tesseract, driven over stdin/stdout.

    A subprocess rather than a wrapper library: it needs no extra dependency, keeps
    the page image in memory instead of writing a picture of someone's resume to a
    temp file, and lets the binary path be configured — which matters because a
    portable Tesseract is not on PATH.
    """

    engine_name: ClassVar[str] = "tesseract"

    def __init__(
        self,
        *,
        command: str,
        languages: str,
        dpi: int = 300,
        max_pages: int = 10,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._command = command
        self._languages = languages
        self._timeout_seconds = timeout_seconds
        self.dpi = dpi
        self.max_pages = max_pages

    def recognize(self, image: Image, *, page_number: int) -> str:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")

        started = time.monotonic()
        try:
            completed = subprocess.run(
                [self._command, "stdin", "stdout", "-l", self._languages],
                input=buffer.getvalue(),
                capture_output=True,
                timeout=self._timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise OCRUnavailableError(
                f"Tesseract was not found at {self._command!r}. Set OCR_COMMAND to the "
                "binary's full path, or OCR_ENGINE=none to disable OCR."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise OCRError(
                f"Tesseract timed out after {self._timeout_seconds:.0f}s on page {page_number}."
            ) from exc

        if completed.returncode != 0:
            # Tesseract's stderr carries diagnostics, never recognized text, so it
            # is safe to quote — truncated, since a warning per line adds up.
            detail = completed.stderr.decode("utf-8", errors="replace").strip()[:200]
            raise OCRError(
                f"Tesseract failed on page {page_number} (exit {completed.returncode}): {detail}"
            )

        text = completed.stdout.decode("utf-8", errors="replace")
        logger.info(
            "ocr: page %d recognized in %d ms (%d chars)",
            page_number,
            int((time.monotonic() - started) * 1000),
            len(text),
        )
        return text


def _installed_languages(command: str) -> set[str]:
    """Ask Tesseract which language packs it has, or say why it cannot be asked."""
    try:
        completed = subprocess.run(
            [command, "--list-langs"],
            capture_output=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise OCRUnavailableError(
            f"OCR_ENGINE=tesseract but no Tesseract binary was found at {command!r}. "
            "Install it and set OCR_COMMAND to its full path, or set OCR_ENGINE=none."
        ) from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OCRUnavailableError(
            f"Tesseract at {command!r} could not be run: {type(exc).__name__}."
        ) from exc

    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()[:200]
        raise OCRUnavailableError(f"Tesseract at {command!r} failed to list languages: {detail}")

    # Older builds answer on stderr, newer ones on stdout. Read both and drop the
    # "List of available languages in ..." header.
    merged = completed.stdout.decode("utf-8", errors="replace")
    merged += completed.stderr.decode("utf-8", errors="replace")
    return {
        line.strip()
        for line in merged.splitlines()
        if line.strip() and not line.startswith("List of available")
    }


def build_ocr_engine(settings: Settings) -> OCREngine | None:
    """Construct the engine named by `settings.ocr_engine`, or None when off.

    The Tesseract branch probes the binary once at startup rather than per
    document, and checks the language packs while it is there: a missing `tha` is
    the quiet failure that matters, because English would keep working and Thai
    would come back as noise. Failing loudly at boot is the same call
    `llm/registry.py` makes for a provider that is selected but not usable.
    """
    match settings.ocr_engine:
        case OCREngineName.NONE:
            return None

        case OCREngineName.TESSERACT:
            requested = {code for code in settings.ocr_languages.split("+") if code}
            available = _installed_languages(settings.ocr_command)
            missing = sorted(requested - available)
            if missing:
                raise OCRUnavailableError(
                    f"Tesseract at {settings.ocr_command!r} is missing language data for "
                    f"{', '.join(missing)}. It has: {', '.join(sorted(available)) or '(none)'}. "
                    "Install the missing traineddata, or set OCR_LANGUAGES to what is there."
                )

            logger.info(
                "ocr: tesseract ready (languages=%s, dpi=%d)",
                settings.ocr_languages,
                settings.ocr_dpi,
            )
            return TesseractEngine(
                command=settings.ocr_command,
                languages=settings.ocr_languages,
                dpi=settings.ocr_dpi,
                max_pages=settings.ocr_max_pages,
                timeout_seconds=settings.ocr_timeout_seconds,
            )
