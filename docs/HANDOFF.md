# Handoff

Written 2026-07-30 at the end of M1, rewritten 2026-08-07 after the Postgres
cutover and the first two M2 items. Read this first when picking the project back
up — then `CLAUDE.md` for the rules and commands, and `docs/PLAN.md` for per-item
milestone status.

> **Start at §11.** A real-world PDF broke three things on 2026-08-07 and they are
> not fixed. One of them strands a resume in a state nothing can recover, and one
> writes resume text into logs and into the API response. Fix those before M2 #3.

---

## 1. Where things stand

**M1 is complete and verified end-to-end.** Upload a PDF resume → get back a
profile in which every field cites the exact text it came from, and anything the
model could not cite is dropped and reported.

**M2 is in progress: items #1, #2 and #8 are done.** Parsing and extraction run on
a background worker with retry, backoff and a dead-letter queue around them. OCR,
DOCX, the two-column fix, MinIO and the SSE progress stream are still open.

### Verified by running it, not only by tests

| Check | Result |
|---|---|
| `pytest -q` | 159 passed, 3 skipped, 1 xfailed (the xfail is deliberate — §7) |
| `TEST_DATABASE_URL=… pytest tests/test_postgres.py` | 3 passed against real Postgres |
| `ruff check` / `ruff format --check` | clean |
| `mypy app` (strict) | clean, 35 files |
| `npm run typecheck` / `lint` / `build` | clean |
| Alembic `upgrade head` → `downgrade base` → `upgrade head` | round-trips on Postgres; `alembic check` finds no drift |
| Browser: register → upload Thai PDF → read profile | 10/10 claims verified, all exact matches (2026-07-30, on SQLite + inline processing) |
| Browser: same with `FAKE_MODE=hallucinating` | 12/13 verified, 7.7% unverifiable, fabricated claim excluded and reported (2026-07-30) |
| CLI with `LLM_PROVIDER=gemini`, every fixture | 0% final hallucination rate, all matches tier-1 exact incl. Thai (2026-08-06 — `docs/llm-providers.md`) |
| API + ARQ worker + Redis + Postgres + live Gemini | upload returns `pending` in ~80 ms; worker extracts in ~8 s; every citation resolves (2026-08-07) |
| Worker stopped, then restarted | the queued job survived and ran on restart, `delayed=11.67s` (2026-08-07) |
| Provider forced down, then recovered | 5 s → 10 s backoff → `dead_lettered`; `POST /retry` then extracted 12 claims on attempt 4 (2026-08-07) |

### Repository state

`main` is on GitHub at <https://github.com/67160366/hirelens>. **The local branch
is 3 commits ahead of `origin/main`** — the Postgres cutover, the ARQ worker, and
the retry/dead-letter work. They have not been pushed, so CI has not run against
them. It was green on the last pushed commit.

CI (`.github/workflows/ci.yml`) runs `ruff check`, `ruff format --check`,
`mypy app`, `pytest -q`, then `npm ci`/`typecheck`/`lint`/`build`. It has no
database, no Redis and no API key, which the next section explains.

---

## 2. The one idea, so the code makes sense

Models cannot count characters, so they are never asked to. The model returns only
a **quote**; the application locates that quote in the source document itself.

```
parse (keep char offsets) → ask the model for quotes → locate every quote → keep only what resolved
```

A quote that cannot be located is a fabrication. This single rule is why the
codebase is shaped the way it is, and it yields three things at once: a guardrail,
explainability (page + char range for the UI to highlight), and a hallucination
rate that costs nothing to produce — no labelled dataset, no baseline to beat.

**Do not weaken this.** If a change would let an unverified claim reach the
response, it is the wrong change.

### The second idea: every dependency has a no-server default

The fake LLM provider, `JSON_VARIANT`'s SQLite branch, and `QUEUE_BACKEND=inline`
all exist so that `git clone && pytest -q` works with no API key, no database
server, no Redis and no spend — and so CI never depends on a third party being up.
This is a load-bearing property, not a convenience. A change that makes the suite
need a server is the wrong change; add an opt-in module like
`tests/test_postgres.py` instead.

---

## 3. Read these files first, in this order

Roughly 30 minutes to get oriented on the pipeline, plus 15 for the job layer.

| Order | File | Why |
|---|---|---|
| 1 | `README.md` | The idea, quick start, honest limitations |
| 2 | **`api/app/pipeline/evidence.py`** | The heart of the project. Three-tier matching, offset maps, rejection reasons. Everything else serves this. |
| 3 | `api/tests/test_evidence.py` | The clearest specification of intended behaviour, including the Thai cases |
| 4 | `api/app/pipeline/parse.py` | The offset contract: `ParsedDocument.text` is the single coordinate space all evidence points into |
| 5 | `api/app/pipeline/extract.py` | How verification is enforced and how the re-ask loop picks a result |
| 6 | `api/app/schemas/extraction.py` + `profile.py` | The two-layer split: what the model returns (quotes only) vs what we store (offsets + stats) |
| 7 | `api/app/llm/fake.py` | Load-bearing infrastructure, not a stub — read before touching the provider seam |
| 8 | `api/app/services/resume_service.py` | The upload path: hash, store, insert, queue |
| 9 | **`api/app/jobs.py`** | The background half: claiming a resume, and the whole retry policy |
| 10 | `api/app/queue.py` | The inline/arq seam, and why the two behave differently on retry |
| 11 | `docs/llm-providers.md` | Provider choice, `FAKE_MODE`, real cost figures |
| 12 | `docs/PLAN.md` | Milestones M2–M6 and the reasoning behind the scope calls |

Skim only when needed: `api/app/api/routes/*`, `api/app/security.py`,
`api/app/storage.py`, `api/app/worker.py` (it is a thin adapter), `web/*`.

---

## 4. What was built

```
api/app/
  pipeline/
    evidence.py      ★ locate quotes in the source; reject what cannot be found
    parse.py           PDF → text + char offsets + page spans; detects scans vs blank
    extract.py         orchestrates: ask → verify → re-ask → keep the cleanest result
    prompts.py         versioned prompts (EXTRACTION_PROMPT_VERSION)
  llm/
    base.py            StructuredExtractor interface, error taxonomy, usage/cost types
    fake.py          ★ rule-based extractor over the real document + failure modes
    gemini.py          Gemini free tier via google-genai
    registry.py        provider selection from settings
  schemas/
    extraction.py      what the model returns — quotes only, no offsets
    profile.py         what we store — offsets, pages, stats, dropped claims
  models/core.py       candidates, resumes, extracted_profiles, llm_call_logs
  services/resume_service.py   upload path: store, insert, queue; and process_resume
  jobs.py            ★ run_resume_job — the unit of background work and the retry policy
  queue.py             JobQueue seam: inline (no server) / arq (Redis)
  worker.py            `arq app.worker.WorkerSettings` — adapter only
  logging_config.py    shared by API and worker so the worker need not import the app
  api/routes/          auth.py, resumes.py
  cli.py               `python -m app.cli <pdf>` — fastest way to see output
web/
  app/page.tsx         auth + upload + poll + result + retry
  lib/api.ts           typed client; `waitForProfile` is the polling loop
  components/Evidence.tsx, ProfileView.tsx, DocumentPane.tsx (citation highlighting)
```

### How one upload flows through the system

Worth reading once, because the request no longer does the work.

1. `POST /resumes` — `upload_resume` checks `Content-Length`, the extension and the
   `%PDF-` magic bytes before anything is stored or billed.
2. `resume_service.ingest_resume` hashes the bytes. A hash this candidate has
   uploaded before resolves to the existing row: same bytes, same result, no second
   extraction. The blob is written, the row is inserted with `status=pending`, and
   the transaction **commits**.
3. Only then is the job enqueued. Before the commit, a fast worker could look up a
   row that is not there yet.
4. The response is `pending` — always, under both queue backends. The client polls
   `GET /resumes/{id}` until the status is neither `pending` nor `processing`.
5. `jobs.run_resume_job` claims the resume (`processing`, `attempts += 1`,
   `last_attempt_at`, `SELECT … FOR UPDATE`), then commits that claim so a second
   delivery of the same resume sees it and skips.
6. `resume_service.process_resume` parses, writes `document_text` and the page
   spans to the row, then extracts and verifies. It does not commit — the job owns
   the transaction.
7. Success: `extracted`, `failed_attempts` reset, one commit for the profile, the
   usage log and the status together.
8. Failure: §6 below.

---

## 5. Design decisions worth not re-litigating

- **Profile stored as one JSON column, stats lifted into real columns.** The
  profile shape is still moving and M3 adds requirement-level tables anyway;
  normalizing twice would be wasted work. The counters are separate columns so cost
  and hallucination queries are plain SQL.
- **`JSON_VARIANT`** in `models/base.py` renders JSONB on Postgres, JSON on SQLite —
  which is what lets the whole test suite run without a database server. The
  Postgres half is pinned by the opt-in `tests/test_postgres.py`.
- **The fake backend is the default provider.** A fresh clone runs every test with
  no API key and no spend, and CI never depends on a third party being up.
- **Client-generated UUID primary keys**, so a caller holds the id before commit.
- **`document_text` is stored verbatim on the resume row.** Evidence offsets index
  into exactly that string; re-parsing later could shift every citation already
  shown to a user.
- **Upload always answers `pending`**, even when the inline queue has already
  finished the work by the time the response is written. One client contract
  instead of one per deployment shape.
- **The job returns a decision (`JobOutcome`), it does not raise arq's `Retry`.**
  That is what keeps `app/jobs.py` free of arq and lets the entire retry policy be
  tested without Redis. `app/worker.py` is the only module that knows arq exists.
- **Two attempt counters, because one cannot do both jobs.** `failed_attempts` is
  the retry budget and is cleared by a success or a manual retry. `attempts` is the
  honest total and never resets — it is also what makes each dispatch's queue job id
  unique, and arq refuses a job id it has recently seen, so a replay sharing the
  failed run's id would be dropped in silence.

---

## 6. The job layer, in more detail

The newest and most intricate part, so it gets its own section.

### Statuses

| Status | Meaning |
|---|---|
| `pending` | Queued, or waiting out a retry backoff. `failure_reason` may explain the last attempt. |
| `processing` | A worker has claimed it. Stuck here means a worker died mid-job. |
| `parsed` | Text extracted, extraction did not finish. **No longer reachable as a resting state**: `process_resume` sets it, but every path out of the job overwrites it before the commit. It survives only on rows written before M2 #2, which is why it is still accepted for retry. |
| `extracted` | A verified profile exists. Terminal, and refuses a retry — redoing it would bill a second call for the profile we already have. |
| `failed` | **This document cannot be processed.** A scanned PDF, a corrupt file, a missing object, a missing API key. Retrying changes nothing. |
| `dead_lettered` | **Transient failures used up the budget.** Worth replaying once the cause is fixed. |

The `failed` / `dead_lettered` split is the point of M2 #2. One status could not
say both "stop asking" and "try me again later".

### Retry policy (`app/jobs.py`)

`is_retryable` is a whitelist of *permanent* errors — `ParseError`,
`ObjectNotFoundError`, `LLMConfigError` — and everything else, including
unrecognised exceptions, counts as transient. That direction is deliberate: an
unfamiliar failure is more likely a blip than a fact about the document, and a
wrong retry costs seconds while a wrong give-up loses the work.

Backoff is `job_retry_base_seconds * 2 ** (failed_attempts - 1)` — 5 s, 10 s, 20 s
— over `job_max_attempts` (3) consecutive failures, then the resume is
dead-lettered with the last error recorded.

`arq`'s own `max_tries` is set to `job_max_attempts + 2` so it never gives up
first: giving up is the job's decision, and it is written down on the resume.

### Two failure paths in `run_resume_job`

`LLMError`, `ParseError` and `ObjectNotFoundError` come from pipeline and storage
code, never from the database, so the session is still usable — whatever
`process_resume` wrote before failing (the parsed text above all) commits together
with the failure bookkeeping, and the retry skips straight to extraction. Any
other exception may have come from the database, so the session is rolled back and
the failure is recorded on a fresh one.

### Replay

`POST /resumes/{id}/retry` clears `failed_attempts` and `failure_reason`, sets
`pending`, and enqueues under a job id derived from the untouched `attempts`.
Accepted for `dead_lettered`, `failed` and `parsed` (the last only for pre-M2 #2
rows — see the status table); 409 for `pending`, `processing` and `extracted`. `ResumeOut.can_retry` tells a client the answer
without reimplementing the rule; the web UI shows a "Try again" button from it.

### What `InlineQueue` does not do

It cannot defer work, and sleeping through a backoff would hold the upload request
open for the length of it. So it never retries: a transient failure leaves the
resume `pending` with the reason recorded, and re-uploading the file picks it up
again. That is a property of running without a queue, not a bug — deployments that
want the retry policy run the ARQ worker.

---

## 7. Deliberate loose ends (not bugs — leave the shape intact)

- **`tests/test_parse.py::TestTwoColumnLayout`** contains a characterization test
  pinning current wrong-but-known behaviour, plus a `@pytest.mark.xfail(strict=True)`
  describing the behaviour we want. When M2 adds column detection, the xfail starts
  passing and *fails the suite* — that is the signal to delete the characterization
  test. Do not "fix" the xfail by removing it.
- **`registry.py` raises for `LLM_PROVIDER=anthropic`** on purpose. An adapter never
  run against the real API is worse than an honest error.
- **Ambiguous citations are flagged, not resolved.** A quote like `Python` appearing
  in both a bullet and a skills list is reported ambiguous rather than guessed.
  A worthwhile refinement is to prefer the skills-section span for skill claims.
- **A resume stuck at `processing` is never reaped.** If a worker dies mid-job
  nothing sweeps the row back to `pending`; the job that redelivers it will skip it
  as already claimed. A visibility timeout on `last_attempt_at` would fix it and
  belongs with M5's observability work.
- **The web client polls.** `api.waitForProfile` is the placeholder M2 #3 replaces
  with SSE; it is deliberately the one place that waits.
- **Statuses are stored as enum *names*** (`EXTRACTED`, `DEAD_LETTERED`), because
  SQLAlchemy's `Enum` persists names by default, while the API serializes the
  values (`extracted`). Pre-existing, harmless, and worth knowing before writing a
  raw SQL query against `resumes.status`.

---

## 8. Environment — read before running anything

**The project path must stay ASCII.** This machine's ANSI codepage is **cp874
(Thai)**. The project originally lived at `D:\งาน\webapp_dev`, and an editable
install (`uv pip install -e .`) wrote a `.pth` file containing that path in UTF-8.
Python's `site` module reads `.pth` files using the system codepage, hit byte
`0x87`, and the interpreter died at startup — the venv became unusable. The project
was moved to `D:\work\webapp_dev` and the problem is gone. Do not move it back
under a non-ASCII path, and prefer ASCII paths for anything Docker bind-mounts.

`api/pyproject.toml` sets `pythonpath = ["."]` for pytest, so the suite works
without an editable install at all.

### Current state of the local stack

| Thing | State |
|---|---|
| Docker | **Installed and running.** `docker compose up -d` brings up `postgres` (pgvector/pg17), `redis` and `minio`. MinIO is up but unused until M2 #7. |
| Database | **Postgres** in Docker (`.env` → `DATABASE_URL`), migrated and verified 2026-08-07. SQLite at `api/var/dev.db` is a commented fallback. The test suite uses its own in-memory SQLite. |
| Test database | `hirelens_test`, created by hand. Only `tests/test_postgres.py` uses it, and it refuses to run against the dev database because it drops every table. |
| Queue | **`arq`** (`.env` → `QUEUE_BACKEND`). Needs `arq app.worker.WorkerSettings` running. `inline` processes in-request with no Redis. |
| LLM provider | **`gemini`** (`gemini-3.6-flash`) in `.env`; live-verified against every fixture on 2026-08-06 — `docs/llm-providers.md`. Tests and CI run on `fake`. |
| Storage | Local filesystem at `var/uploads` |

### Start it

```bash
docker compose up -d               # from the repo root

cd api
uvicorn app.main:app --reload      # http://127.0.0.1:8000  (/docs for OpenAPI)
arq app.worker.WorkerSettings      # a second terminal; only for QUEUE_BACKEND=arq

cd ../web
npm run dev                        # http://localhost:3000
```

**Without the worker running, uploads sit at `pending` forever.** Re-uploading the
same file re-queues it, so starting the worker late still gets the work done.

Fastest sanity check, no servers needed — it goes straight to the pipeline and
touches neither the database nor the queue:

```bash
cd api && python -m app.cli tests/fixtures/resume_th.pdf
```

To see the dropped-claims path: set `FAKE_MODE=hallucinating` in `.env`, restart
the API and the worker, upload again. To see the dead-letter path: set
`FAKE_MODE=unavailable` and watch the worker log.

### The test suite, file by file

| File | What it pins |
|---|---|
| `test_evidence.py` | Three-tier matching, rejection reasons, Thai. The specification. |
| `test_parse.py` | Offsets, page spans, scan detection, the two-column xfail |
| `test_extract.py` | The re-ask loop and how it picks a result |
| `test_llm.py` / `test_gemini.py` | The provider seam; Gemini's contract via mocks |
| `test_api.py` | Auth, upload gates, reading a profile back |
| `test_resume_service.py` | The duplicate-upload race, blob cleanup, PII-safe logging |
| `test_worker.py` | Upload enqueues; the job runs; the arq adapter |
| `test_retry.py` | Error classification, backoff, dead-lettering, replay |
| `test_postgres.py` | JSONB, Thai round-trip, JSON queries. **Opt-in**, needs `TEST_DATABASE_URL` |
| `test_config.py` | Settings validation, including the JWT-secret refusal |

---

## 9. Next steps

**All setup items are done.** Docker is installed, development runs on Postgres,
the JSONB path is verified, Gemini has run live, and the queue is real.

**Next is M2 #3.** In dependency order (live status in `docs/PLAN.md`):

| # | Work | Notes |
|---|---|---|
| 1 | ~~ARQ worker + Redis~~ **done** | `app/jobs.py` (work), `app/queue.py` (seam), `app/worker.py` (entrypoint) |
| 2 | ~~Job state, retry with backoff, dead-letter queue~~ **done** | §6 above |
| 3 | SSE progress endpoint; wire the web UI's "Parsing…" state to it | Replace `api.waitForProfile` in `web/lib/api.ts` — the one place that waits. The statuses it needs already exist; `processing` is the event worth streaming |
| 4 | OCR fallback for scans (Tesseract + `tha`) | `ParsedDocument.pages_without_text` is already the work list; `resume_scanned.pdf` and `resume_mixed_scan.pdf` are real image-based fixtures. Note this turns a `failed` scan into work: `NoTextLayerError` is caught in `process_resume`, which marks the row `failed` and returns before the retry policy ever sees it |
| 5 | DOCX parser | `parse_document_bytes` already dispatches on extension and raises `UnsupportedFileTypeError`; the upload route's `ALLOWED_SUFFIXES` gate also needs opening |
| 6 | **Two-column fix** via bbox column detection | The strict xfail defines "done" |
| 7 | MinIO storage backend | `build_storage` has the `MINIO` branch stubbed with a clear error. The worker and the API both build storage independently, so both pick it up |
| 8 | ~~Evidence viewer~~ **done** — text-layer only | `web/components/DocumentPane.tsx` highlights every citation in `document_text` and scrolls to the one clicked. A true pdf.js overlay on the rendered page is *not* done: it needs bbox geometry, which `ParsedDocument` does not keep, plus an endpoint serving the original file. Do it with #6, which needs the same bbox extraction. |

Two things worth doing whenever convenient, neither blocking:

- **Push the three local commits** and confirm CI is green on them.
- **Re-do the browser walkthrough.** The last one was on 2026-07-30, before the
  queue existed; the polling loop and the "Try again" button have been verified at
  the HTTP level but not in a browser (the Chrome extension was not connected).

M3 onward (matching engine, backend depth, frontend, ship) is in
[`docs/PLAN.md`](PLAN.md), which also tracks the status of the items above.

---

## 10. Things to be careful about

- **Never let an unverified claim into a response.** Add to `dropped`, not to the
  profile.
- **Do not have the model produce offsets.** It is the mistake the whole design
  avoids.
- **Do not make the test suite need a server.** The no-server default is why CI is
  simple and a fresh clone works. Opt-in modules, like `tests/test_postgres.py`, are
  the way to test a real backend.
- **Never log or print document text.** Resumes are PII: ids, counts and durations
  only. `test_resume_service.py` pins this, and the storage key counts too — it
  embeds the candidate id and the file's content hash.
- **`ruff format` is enforced in CI.** Run it before pushing.
- **Test data is synthetic and must stay that way.** No real person's resume goes in
  this repo. Regenerate fixtures with `python api/tests/fixtures/generate.py`
  (needs a Thai-capable font locally; the generated PDFs are committed so CI does
  not need one).
- **If you add a paid provider, update the price table** in the adapter. A stale
  price silently corrupts every cost figure.
- **Enqueue after the commit, never before.** The worker looks the row up by id.
- **Scope discipline on evaluation.** Ranking metrics against a BM25/embedding
  baseline are deliberately *out* of the critical path (M6, one-week timebox). The
  measurable-for-free metrics — hallucination rate, parse success, cost per
  document — are in. This was a considered decision to avoid unbounded work; don't
  quietly promote the baseline comparison into M2 or M3.

---

## 11. Open bugs — fix these before M2 #3

Found 2026-08-07 by uploading a real-world Thai resume template (a designer-tool
PDF, 443 KB, 1 page) through the browser against Postgres + the ARQ worker + live
Gemini. **None of them is fixed.** They are one incident, but three independent
defects, and the order they are fixed in matters — see the warning on #3.

### What happened

The pipeline succeeded completely: the PDF parsed, Gemini ran twice over 34 s, and
verification produced **5 claims with 0 dropped**. Persisting it then failed on the
last statement and the whole transaction rolled back. All of that work was lost,
the resume was left unrecoverable, and the resume's text ended up in the log.

```
resume 68d212a0-…: extracted — 5 verified, 0 dropped, 2 attempt(s), 34188 ms
34.55s ! resume:68d212a0-…:0:process_resume failed, DBAPIError:
  asyncpg.exceptions.CharacterNotInRepertoireError:
  invalid byte sequence for encoding "UTF8": 0x00
```

### Bug 1 — NUL characters reach the database, and no test can see it

`pdfplumber` extracted 8 `U+0000` characters from that PDF — positions where the
embedded font has no usable ToUnicode mapping, so a Thai tone mark came back as
NUL (`วิทยาลัยที\x00คุณจบ`). Reproducible on demand:

```python
doc = parse_document_bytes(data, filename="x.pdf")
# chars: 1751, pages: 1
# control chars: {'0x0': 8}
# NUL positions: [585, 1042, 1441, 1630, 1684, 1707, 1736, 1745]
```

**Postgres cannot store `U+0000` in a text column. SQLite can.** Every one of the
159 tests runs on SQLite, and the opt-in `tests/test_postgres.py` uses clean
synthetic fixtures, so both are blind to it. This is exactly the class of defect
the Postgres cutover was meant to expose; it did not, because the test data is too
well-behaved.

*Fix:* strip `U+0000` in `_assemble` (`api/app/pipeline/parse.py`), at the point
that already runs `unicodedata.normalize("NFC", raw)` — that is *before* the page
spans are computed from `len(page_text)`, so removing characters there shifts no
offsets. This does not violate the verbatim-`document_text` rule: that rule forbids
re-parsing or re-normalizing text **already stored**, not cleaning at parse time.

### Bug 2 — a failed commit strands the resume where nothing can reach it

In `run_resume_job` (`api/app/jobs.py`) the final `await session.commit()` sits
**outside** the `try/except` that implements the retry policy. When the commit
itself fails, the exception escapes to arq and none of the bookkeeping runs:

```
status=PROCESSING  attempts=1  failed_attempts=0  failure_reason=(empty)
```

Every route out is then closed. `_claim` skips `processing`, so redelivery is a
no-op; `POST /resumes/{id}/retry` refuses `processing` with 409; and re-uploading
the same bytes dedupes to the row without re-queueing, because
`_requeue_if_stalled` only fires for `pending`. The web client polled 168 times and
gave up at its two-minute timeout — that is what the user sees.

*Fix:* move that commit inside the `try`, so a persistence failure goes through
`_record_failure_on_a_fresh_session` like any other unexpected error. Worth adding
the visibility timeout listed in §7 as well, so a worker that dies mid-job cannot
strand a row either.

*The stuck row from this incident is still in the dev database*
(`68d212a0-4f84-4100-bdac-351481177581`) and needs its status reset by hand before
it can be retried.

### Bug 3 — resume text leaks into logs and into the API response

SQLAlchemy's `DBAPIError` string embeds the failing statement's parameters, which
include `document_text`. The worker log from this incident holds a real person's
name, work history and education in plaintext. `CLAUDE.md` forbids exactly this:
*"Never log or print document text or personal data — resumes are PII."*

**Fix this together with bug 2, or fixing bug 2 alone makes it worse.** Once the
exception is caught, `_record_failure` builds its reason as
`f"{type(error).__name__}: {error}"` and writes it to `failure_reason` — so the
resume text would travel from the log into the **database** and out through the
API to any client that reads the resume.

*Fix:* for unexpected exceptions, record and log the exception's **type name
only**, never its message. Known pipeline errors (`ParseError`, `LLMError`) carry
messages written by this codebase and stay safe to include.

### Fix order and the test that should have caught this

1. `parse.py` — strip `U+0000` (bug 1).
2. `jobs.py` — commit inside the `try` **and** type-name-only failure reasons
   (bugs 2 and 3, together).
3. Tests: a fixture whose extracted text contains `U+0000`; a case in
   `tests/test_postgres.py` proving it round-trips on real Postgres; and a case
   proving a failing commit ends at `dead_lettered` rather than stranded at
   `processing`.
4. Reset the stuck row, then re-upload the same PDF to confirm end to end.

The wider lesson worth acting on: the synthetic fixtures are all well-formed, so
whole classes of real-world PDF damage — NUL bytes, broken ToUnicode maps, mixed
encodings — cannot appear in the suite. A fixture generated to be *malformed* on
purpose belongs alongside the clean ones.
