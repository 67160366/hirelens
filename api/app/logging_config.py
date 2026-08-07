"""Logging setup, shared by the API and the worker.

Its own module so the worker process does not have to import the FastAPI app just
to configure logging.
"""

from __future__ import annotations

import logging


def configure_logging() -> None:
    """One root handler at INFO. Resumes are PII: log ids and counts, never text."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
