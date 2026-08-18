# CLAUDE.md

HireLens — resume screening where every claim the system makes cites the exact text
it came from. FastAPI (`api/`) + Next.js (`web/`). Thai and English resumes.
**M1–M5 are all closed** (M5 on 2026-08-16), each scoped with the owner rather than
reconstructed. **M6 was reviewed on 2026-08-16 and closed unbuilt** — not deferred: a
ranking evaluation against a BM25 baseline is a category error the codebase already warns
about (`pipeline/retrieval.py:21-24`), the embedding half is a paid adapter under the
hard rule below, and a gold set over nine synthetic fixtures would be marking its own
homework. `docs/PLAN.md`'s M6 section carries all four reasons. **Do not reopen it by
treating it as a backlog item**; if it is revisited, the two honest shapes are named
there. The authoritative per-item status is the table in `docs/PLAN.md`. Orientation for a
new session: this file, then `docs/HANDOFF.md` §3 (reading order), then `docs/PLAN.md`.

**There is no milestone in progress.** `useAuth` was rewritten onto
`useSyncExternalStore` on 2026-08-16, so **the session is an external store and no
component copies it into state** — `web/lib/auth.ts` is the only thing that touches
`localStorage`, and two components on one page can no longer disagree about who is
signed in. The **refresh-token denylist landed the same day** (migration `0011`,
`services/token_service.py`), so `POST /auth/logout` is real, a spent refresh token is
genuinely single-use, and rotating `JWT_SECRET` is no longer the only revocation there
is. **A password change now ends every session on every device** (2026-08-18, migration
`0012`): `Candidate.token_epoch` is the generation a token was minted under, and a
mismatch is refused, so one integer ends sessions nothing ever recorded.
**`decode_token` and `token_service.assert_live` must always be called together** —
verifying a token without checking the denylist accepts one somebody signed out, and it
is the pairing that makes any of it true. `assert_live` takes the account row as a
**required** argument so that pairing stays two things rather than three; mypy refuses a
call that has not looked up whose token it is. The one named item left is **httpOnly
cookies** instead of `localStorage`, which answers XSS token theft rather than
revocation, and which needs a decision about whether bearer auth survives alongside it —
every `curl` in `docs/RUNBOOK.md` uses one.

M5's organizing idea, the same shape as the two below: **every number on an
observability screen is a query over rows the system already wrote, and can name the
rows it came from.** A dashboard reports; it never re-asks, and nothing on it spends
a model call.

**That check ran on 2026-08-13 and found seven defects, four of them blocking** — in a
slice where every gate was green and every API call had been verified. `HANDOFF.md` §1
has them. The rule it bought: **a slice is done when somebody has used it, not when its
calls are verified.** Drive the browser *inside* the slice, the way M3's slice 5 did.

M4's governing rule, the same shape as the one below: **a state transition is a claim
about a person, so it is derived from an append-only event log rather than asserted.**
Nothing may write `Application.state` without appending the event that caused it —
`app/services/application_service.py` is the only writer of both, and replaying
`application_events` must reproduce the column. Two rules fall out and are enforced in
`app/applications.py`: a shortlist is reachable only from `screened` and records the
screening id it rests on, and a rejection requires a reason. The log is ordered by a
stored `position`, never by `created_at` — SQLite's timestamps have one-second
granularity and the tiebreak would be a random UUID.

And M4's other rule, easy to undo by accident: **a role gates a route (403), while
ownership gates a row (404).** Never merge them — a 403 on an id confirms the id
exists, which is the account-enumeration answer `_owned_job` and `_owned_resume` are
written to avoid. `require_role` in `api/deps.py` is the only place a 403 belongs.

## The one idea — never weaken it

Models cannot count characters, so they are never asked to. The model returns only
**quotes**; the application locates each quote in the source document
(`api/app/pipeline/evidence.py`). A quote that cannot be located is a fabrication:
it is dropped, reported in `dropped`, and counted in the hallucination rate.

- **Never let an unverified claim into a response.** Add it to `dropped` instead.
- **Never ask the model to produce character offsets or page numbers.** That is the
  exact mistake this design exists to avoid.
- If a change would let an unverified claim reach the response, it is the wrong change.

## Hard rules

- **`test_columns_should_read_one_after_the_other` in `api/tests/test_parse.py`
  must stay.** It carried a strict xfail that defined "done" for the two-column fix;
  column detection landed in M2 #6, the xfail started passing and failed the suite
  on purpose, and the paired characterization test was deleted — the marker with it.
  The assertion itself is now a normal passing test and stays under that name.
  A page that is not clearly multi-column must still parse byte-identically to
  before (`api/app/pipeline/layout.py` returns `None`); that is what keeps every
  citation already shown to a user pointing where it did.
- **`LLM_PROVIDER=anthropic` raises on purpose** (`api/app/llm/registry.py`). An
  adapter never run against the real API is worse than an honest error. Implement it
  only together with a real key and a live verification run.
- **Test data is synthetic only.** No real person's resume enters this repo.
  Fixtures are generated by `api/tests/fixtures/generate.py` and committed.
- **The project path must stay ASCII.** This machine's codepage is cp874 (Thai); a
  Thai path once bricked the venv via a `.pth` file (`docs/HANDOFF.md` §6).
- **Paid providers must keep their price table current** in the adapter — a stale
  price silently corrupts every cost figure — and, like `anthropic`, a new paid
  adapter lands only together with a live verification run recorded in
  `docs/llm-providers.md`.
- **`document_text` is stored verbatim** on the resume row and every evidence offset
  indexes into exactly that string. Never re-parse or re-normalize stored text —
  it would shift every citation already shown to a user.
- **OCR text is substituted into the page list *before* `_assemble` measures spans**
  (`api/app/pipeline/parse.py`). That is what lets a rescued page carry ordinary
  offsets and leaves evidence, page mapping and highlighting untouched. Recognizing
  text into an already-assembled document would shift every offset after that page.
- **The fake provider (`api/app/llm/fake.py`) is load-bearing infrastructure**, not a
  stub — the whole suite and CI depend on it. Read it before touching the provider seam.
- **Never log or print document text or personal data** — resumes are PII.
- **Erasure deletes stored files before rows, and deletes nothing if a file refuses**
  (`api/app/services/privacy_service.py`). Rows-first leaves an object in the bucket
  that nothing points at — undiscoverable, and so unerasable. A row whose file is
  missing is already a handled state. Do not "simplify" the order.
- **`PRAGMA foreign_keys=ON` in `api/app/db.py` is load-bearing.** SQLite ignores
  every `ON DELETE` clause without it, so a cascade that works on Postgres does
  nothing there — and the whole test suite runs on SQLite.

## Commands

All Python commands run from `api/` inside its venv — activate it first
(`.venv\Scripts\activate` on Windows, `source .venv/bin/activate` elsewhere) or
prefix each command with `.venv/Scripts/python.exe -m` (Windows) /
`.venv/bin/python -m` — the bare names are not on PATH:

```bash
pytest -q                                   # full suite; no DB, no API key, no Tesseract
TEST_DATABASE_URL=postgresql+asyncpg://hirelens:hirelens@localhost:5432/hirelens_test \
  pytest tests/test_postgres.py -q          # opt-in: the JSONB path on real Postgres
OCR_TESSERACT_CMD=C:\Users\golfv\tesseract.exe \
  pytest tests/test_ocr_tesseract.py -q     # opt-in: the real Tesseract, including Thai
TEST_MINIO_ENDPOINT=http://localhost:9000 \
  pytest tests/test_minio.py -q             # opt-in: the storage contract on real MinIO
TEST_LIVE_LLM=1 \
  pytest tests/test_judge_live.py -q        # opt-in: judging against the real provider.
                                            # SPENDS QUOTA, and is gated on this flag
                                            # rather than on a key, which .env has
ruff check app tests migrations             # lint   — enforced in CI
ruff format app tests migrations            # format — enforced in CI (--check)
mypy app                                    # strict — enforced in CI
python -m app.cli tests/fixtures/resume_th.pdf   # fastest end-to-end sanity check
python -m app.cli tests/fixtures/resume_th.pdf --requirement skill:Python   # …and judging
uvicorn app.main:app --reload               # API on :8000, /docs for OpenAPI
alembic upgrade head                        # migrations (against DATABASE_URL)
arq app.worker.WorkerSettings               # the job worker (needs QUEUE_BACKEND=arq + Redis)
```

From `web/`: `npm run dev` (:3000), `npm run typecheck`, `npm run lint`, `npm test`
(vitest), `npm run build`.

## How to work here

1. **Orient before editing.** Read `docs/HANDOFF.md` §3 in order (~30 min) before
   touching the pipeline. `evidence.py` is the heart; `test_evidence.py` is its spec.
2. **Plan first for significant work.** Write the intended slice down (or use plan
   mode) before coding; check it against `docs/PLAN.md` scope.
3. **Do not re-litigate the design decisions in `docs/HANDOFF.md` §4** — profile as
   one JSON column with stats lifted out, `JSON_VARIANT`, fake as default provider,
   client-generated UUIDs, verbatim `document_text`.
4. **Ship vertical slices.** Each commit lands one working capability with its
   tests. Commit messages are imperative and name the outcome, e.g. "Add the
   evidence validator: locate every quote or drop the claim".
5. **Definition of done:** `pytest -q`, `ruff check`, `ruff format --check`, and
   `mypy app` all green (plus `npm run typecheck && npm run lint && npm test` if
   `web/` changed);
   new behaviour pinned by tests; `docs/PLAN.md` status updated, and `docs/HANDOFF.md`
   refreshed when a milestone completes.
6. **Scope discipline.** Milestones live in `docs/PLAN.md`. The baseline-ranking
   evaluation was M6 and is **closed unbuilt** — do not resurrect it as a "quick win",
   and do not let a retrieval score be presented next to a ranking score anywhere, which
   is the confusion that killed it.
7. **Leave the session readable.** Commit each finished slice the moment its gates
   are green rather than batching — a session that ends early should never hold work
   that only a diff explains. If a run is cut short, the dated `docs/NOTES.md` entry
   names the uncommitted files, the gate numbers actually run, and the next step. And
   a tool that died on a quota limit produced no coverage: its empty result is not a
   clean result, and reporting it as one is the same mistake as a test that cannot
   fail.

## Map

Three files carry the weight: `api/app/pipeline/evidence.py` locates quotes and
rejects what it cannot find, `api/app/llm/fake.py` is load-bearing test
infrastructure rather than a stub, and `api/app/jobs.py` holds the background work
and the whole retry policy. Annotated tree of everything else: `docs/HANDOFF.md` §4.

**`api/app/pipeline/retrieval.py` is the one module allowed to be approximate**, and
only because it makes no claim about anyone: it orders resumes by how worth judging
they look, and deleting it would change no verdict. It returns *every* document,
ordered — a retriever that filtered would drop a person before anyone looked. Do not
let its score reach a verdict, and do not let it start filtering.

Environment quirks: dev runs on Postgres + Redis from `docker compose up -d` +
local storage (`var/uploads`); SQLite (`api/var/dev.db`) is a commented fallback
in `.env`. `STORAGE_BACKEND=minio` switches to the MinIO in compose, which creates
its bucket in a one-shot service — a missing bucket is refused at startup. The test suite runs on its own
in-memory SQLite with `QUEUE_BACKEND=inline` and never needs a server. `.env`
selects the LLM provider — `fake` needs no key; `FAKE_MODE=hallucinating` demos
the dropped-claims path.

OCR is **off by the code's default** (`OCR_ENGINE=none`) because Tesseract is a
system binary and CI will never have one — the same reasoning as the fake provider.
**This machine's `.env` already turns it on**, with `OCR_ENGINE=tesseract` plus
`OCR_COMMAND=C:\Users\golfv\tesseract.exe`: its Tesseract is a portable install and
is **not on PATH**, so the bare name will not resolve. So a scanned upload here is
read rather than reported, which a fresh clone's would not be — and inside the
container it resolves differently again, from the bare name the API image installs
on `PATH`. A missing language pack is refused at startup rather than
returning noise for Thai, so `OCR_LANGUAGES` must name packs that are installed
(`eng`, `tha`, `osd` are). A page whose mean per-word confidence falls below
`OCR_MIN_CONFIDENCE` (75) is refused rather than reported — a blurred scan yields
plenty of characters, they are simply the wrong ones. That number came from
`api/tests/tools/ocr_degradation.py`; change it only with new measurements.

Upload stores the file, queues the work and answers `pending`; clients follow
`GET /resumes/{id}/events` until the status is neither `pending` nor `processing`,
and fall back to polling `GET /resumes/{id}` when the stream ends without a
verdict. Two failure statuses: `failed` means the document cannot be processed, while
`dead_lettered` means transient failures used up the retry budget and it is worth
replaying via `POST /resumes/{id}/retry`. Both, and why the split matters, are in
`docs/HANDOFF.md` §6.

A row held at `processing` past `JOB_VISIBILITY_TIMEOUT_SECONDS` (900) means the
worker died rather than failed. `jobs.reclaim_stalled` sweeps those on an arq cron,
**through `decide_retry` rather than a status reset** — that is what stops a document
which kills its worker every time from looping reap → requeue → die. The same row is
retryable by hand from the API, which is the only route under `QUEUE_BACKEND=inline`.
