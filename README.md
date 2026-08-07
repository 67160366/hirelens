# HireLens

Resume screening where **every claim the system makes cites the exact text it came
from** — and anything it cannot cite is dropped and reported rather than shown.

Built from the HR Tech user journey (#19) in `userjourneysthailand.md.pdf` — a
source document kept out of the repository (it may contain third-party content),
so a fresh clone will not have it. Its pain points name the problem directly: *"เรซูเม่ไม่ผ่านการคัดกรองอัตโนมัติ (ATS)
โดยไม่รู้สาเหตุ"* — candidates rejected by automated screening with no explanation.

Handles Thai and English resumes.

---

## The one idea

Models cannot count characters, so they are never asked to. The model returns only
a **quote**; the application locates that quote in the source document itself.

```
parse (keep char offsets) → ask the model for quotes → locate every quote → keep only what resolved
```

A quote that cannot be located is a fabrication. That single rule produces three
things at once:

1. **A guardrail.** Unverifiable claims never reach a reviewer.
2. **Explainability.** Every field carries a page number and character range, which
   is what the UI renders — and, from M2, highlights on the PDF.
3. **A metric, for free.** Counting rejected quotes gives a hallucination rate with
   no labelled dataset and no baseline to beat.

The implementation lives in [`api/app/pipeline/evidence.py`](api/app/pipeline/evidence.py).
Matching runs in three tiers — verbatim, then whitespace-insensitive, then
whitespace-stripped, the last mainly to rescue Thai, which PDF extraction likes to
break mid-word. The tier that matched is recorded, so a run full of loose matches
points at a parser problem rather than hiding one.

---

## Status

**M1 complete.** Upload a PDF, get back a profile in which every field is traceable
to the source.

| Milestone | Scope |
|---|---|
| **M1 ✅** | Parse (PDF, offsets, Thai), extract, verify evidence, retry on rejection, auth, upload API, web UI |
| M2 | Async worker + queue, OCR for scans, DOCX, two-column layout fix, MinIO, PDF viewer with highlighted spans |
| M3 | Job requirements, hybrid retrieval, requirement-level judging, ranking |
| M4 | Application state machine, idempotency, race conditions, RBAC, PDPA |
| M5 | Full recruiter UI, observability, deploy |

Picking the project up after a break: **[docs/HANDOFF.md](docs/HANDOFF.md)** — what
exists, which files to read in what order, and what to do next. The full milestone
plan with per-item status lives in [docs/PLAN.md](docs/PLAN.md).

---

## Quick start

Requires Python 3.11+, Node 22+, and (optionally) Docker.

```bash
cp .env.example .env          # defaults need no API key and no database server

cd api
uv venv --python 3.11
uv pip install -e ".[dev]"
alembic upgrade head          # SQLite by default; see .env for Postgres
uvicorn app.main:app --reload

cd ../web
npm install
npm run dev                   # http://localhost:3000
```

The web app expects the API at `http://localhost:8000`; if it lives elsewhere,
`cp web/.env.local.example web/.env.local` and set `NEXT_PUBLIC_API_BASE`.

For Postgres, Redis and MinIO instead of SQLite and the local filesystem — which
is what this project develops against, and what it deploys on:

```bash
docker compose up -d                       # postgres (pgvector), redis, minio
# swap DATABASE_URL to the Postgres line in .env and set QUEUE_BACKEND=arq, then:
cd api
alembic upgrade head
arq app.worker.WorkerSettings              # in its own terminal, next to uvicorn
```

With `QUEUE_BACKEND=inline` (the default) there is no worker and no Redis: the
upload request does the work itself. The API behaves the same either way — it
answers `pending` and the client polls.

### Try it without the web app

```bash
cd api
python -m app.cli tests/fixtures/resume_th.pdf
```

```
Name       สมชาย ใจดี
             ↳ p1 0-10 "สมชาย ใจดี"
Seniority  senior
             ↳ p1 11-72 "วิศวกรซอฟต์แวร์อาวุโส | somchai.j@example.com | กรุงเทพมหานคร"
...
verified 10/10  hallucination_rate 0.00%  attempts 1  cost $0.000000
match kinds: exact=10
```

---

## Architecture

```
Next.js (App Router, TS, Tailwind)
   │  REST
   ▼
FastAPI ──► PostgreSQL (+pgvector, for M3)   ← SQLite works for local dev
   │        Redis          (job queue)
   │        MinIO / S3     (M2; local filesystem today)
   │
   └─ enqueue ─► ARQ worker            ← or QUEUE_BACKEND=inline, no Redis
                    ▼
        Pipeline: parse → extract → verify evidence → score (M3)
                             │
                             └─► LLM provider (fake | gemini)
```

Upload stores the file, queues the work and returns a `pending` resume; the client
polls `GET /resumes/{id}` until it settles. An SSE progress stream replaces the
polling in M2 #3.

### Provider-agnostic by design

`LLM_PROVIDER` selects the backend. The default, `fake`, is a rule-based extractor
that reads the actual document, so **the entire test suite and a full local demo
run with no API key and no spend** — and CI never depends on a third-party API
being up. `gemini` uses Gemini's free tier for real extraction. See
[docs/llm-providers.md](docs/llm-providers.md) for costs and how to add another.

The fake is not a stub returning canned data: it extracts real text and quotes it,
so evidence verification behaves exactly as it does in production. It also has a
`hallucinating` mode that cites text which is not in the document, which is how the
dropped-claims path is tested and demoed.

---

## What is measured

Recorded per document, with no labelling required:

| Metric | Source |
|---|---|
| Hallucination rate | Share of quotes the resolver could not locate |
| Verified vs dropped claim counts | Same |
| Match-kind breakdown | Which of the three matching tiers each quote needed |
| Model calls per document | Retries spent re-asking about rejected quotes |
| Cost and latency per document | `llm_call_logs`, one row per call, with prompt version |

Deliberately **not** claimed: ranking quality against a BM25 or embedding baseline.
That needs a labelled gold set, and a project that stakes its success on beating a
baseline it has not measured invites unbounded work. It is scoped as optional
(M6) behind a one-week timebox.

---

## Known limitations

Recorded honestly, with tests pinning current behaviour so fixes are visible:

- **Two-column PDFs interleave.** pdfplumber reads in visual order, so a job title
  from the right column can land beside contact details from the left. Quotes stay
  truthful; adjacency misleads. Pinned by
  `tests/test_parse.py::TestTwoColumnLayout`, including a `strict` xfail that will
  start passing when M2 adds bbox column detection.
- **Scanned PDFs are rejected, not read.** Detected and reported with an actionable
  message (and distinguished from genuinely blank documents, which OCR cannot
  rescue). OCR lands in M2.
- **Ambiguous citations are flagged, not resolved.** A quote such as `Python` that
  appears in both a bullet and a skills list is reported as ambiguous rather than
  guessed at.
- **Extraction runs inline in the request.** Fine for a fake or a fast model; M2
  moves it to a worker.
- **The access token is kept in `localStorage`,** which is XSS-readable. Acceptable
  for a two-origin dev setup; the production answer is an httpOnly cookie.

## Test data

All resumes and job descriptions in this repository are **synthetic**. No real
person's resume is included. The PDF fixtures are generated by
[`api/tests/fixtures/generate.py`](api/tests/fixtures/generate.py) and committed, so
tests do not depend on a Thai-capable system font being installed.

## Tests

```bash
cd api && pytest -q            # 130 tests, no database or API key needed
cd web && npm run typecheck
```

CI runs lint, format, types, tests, a migration up/down round-trip, and the web
build.
