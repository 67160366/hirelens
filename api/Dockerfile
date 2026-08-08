# The API and the ARQ worker ship as one image: `app/worker.py` is a thin adapter
# over `app/jobs.py`, so the two processes differ only in the command they run.
# Building them separately would let their dependencies drift apart silently.
#
# Python 3.11 matches what CI installs (`uv sync --python 3.11`). The image should
# not be the one place this project runs on an interpreter it is never tested on.

FROM python:3.11-slim AS builder

# UV_COMPILE_BYTECODE trades build time for startup time, which is the right way
# round for a long-lived server. UV_LINK_MODE=copy silences uv's warning about
# hardlinking across the mounted cache and the image filesystem.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

RUN pip install --no-cache-dir uv

WORKDIR /app

# Manifests first, so editing application code does not invalidate the dependency
# layer. `--locked` fails loudly if pyproject.toml and uv.lock have drifted —
# the same guarantee CI relies on.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

COPY . .
RUN uv sync --locked --no-dev


# --- runtime ---------------------------------------------------------------
FROM python:3.11-slim AS runtime

# Tesseract with Thai and English. On the development machine this is a portable
# install that is deliberately not on PATH (docs/HANDOFF.md §8), which is why
# OCR_COMMAND exists; in the image it is simply `tesseract`. OCR still defaults to
# off — `build_ocr_engine` probes the binary *and* its language packs at startup,
# so enabling it here is one environment variable and fails loudly if wrong.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-tha \
    && rm -rf /var/lib/apt/lists/*

# Resumes are PII and this process reaches the network. It does not need root.
RUN useradd --create-home --uid 1000 hirelens

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY --from=builder --chown=hirelens:hirelens /app /app

# `Settings.storage_path` resolves a relative STORAGE_DIR against REPO_ROOT, which
# is computed as three parents up from app/config.py — that is the repository root
# on a checkout but `/` in this image. So the compose file passes an absolute
# STORAGE_DIR pointing here, and this directory is a volume.
RUN mkdir -p /data/uploads && chown -R hirelens:hirelens /data

USER hirelens
EXPOSE 8000

# urllib rather than curl: it is already in the image, so the healthcheck adds no
# packages and no attack surface.
HEALTHCHECK --interval=10s --timeout=5s --start-period=40s --retries=6 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


# --- test ------------------------------------------------------------------
# Adds the dev extra so the suite can run against the image itself. Not part of
# the runtime image and not built by `docker compose up`; Docker only builds the
# stages a target needs. Build it explicitly:
#   docker build --target test -t hirelens-api-test ./api && docker run --rm hirelens-api-test
FROM builder AS test
RUN uv sync --locked --extra dev
CMD ["uv", "run", "--no-sync", "pytest", "-q"]
