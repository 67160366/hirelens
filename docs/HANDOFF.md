# Handoff

Written 2026-07-30 at the end of M1, rewritten 2026-08-07 after the Postgres
cutover, again 2026-08-08 when M2 completed, and updated the same day when M3's
scope was agreed and its first slice landed. Read this first when picking the
project back up — then `CLAUDE.md` for the rules and commands, and `docs/PLAN.md`
for per-item milestone status. Short dated session notes and owner advice live in
`docs/NOTES.md`.

---

## 1. Where things stand

**M1 is complete and verified end-to-end.** Upload a PDF resume → get back a
profile in which every field cites the exact text it came from, and anything the
model could not cite is dropped and reported.

**M2 is complete.** Parsing and extraction run on a background worker with retry,
backoff and a dead-letter queue around them; the web client follows a resume over a
progress stream instead of polling for it; a scanned page is recovered with OCR
instead of being a permanent failure, and refused rather than misread when the
recognition is not trustworthy; `.docx` uploads are read as well as PDFs; a
two-column page is read one column at a time; and uploads can live in object storage
instead of on a disk.

Three long-standing items came off the watch list with it: the CI actions are off
Node 20, there is finally a PDF in the fixtures that is broken on purpose, and the
OCR confidence question has an answer with numbers behind it.

**M3 — the matching engine — is under way.** Its scope was reviewed with the owner
on 2026-08-08 and is no longer a draft: the agreed shape, the four decisions behind
it and the six slices are in `docs/PLAN.md`. **Slices 1 and 2 are done** — a job
posting and its requirements are first-class rows with CRUD behind them, and a
resume can be judged against those requirements with every match cited. The rest, in
order: screening on the worker, ranking, a thin UI, retrieval.

The one idea to carry into the remaining slices, now shipped rather than planned:
**the model is never asked for a verdict.** It is asked only for quotes showing a
requirement is met, and the application derives `met` (a quote resolved) or
`not_evidenced` (none did) from what `EvidenceResolver` could locate — so judging
inherits the guardrail, the `dropped` list and the hallucination rate without any of
them being re-implemented or weakened. §5 says why `not_met` is deliberately not
available.

### Verified by running it, not only by tests

| Check | Result |
|---|---|
| `pytest -q` | 339 passed, 26 skipped, **no xfail** — 270 at the close of M2, plus 25 for M3 slice 1, 12 for `page_spans` and 32 for judging. The two-column xfail started passing on 2026-08-08, which was its job (§7) |
| `TEST_MINIO_ENDPOINT=… pytest tests/test_minio.py` | 9 passed against the MinIO in compose |
| `TEST_DATABASE_URL=… pytest tests/test_postgres.py` | 4 passed against real Postgres |
| `OCR_TESSERACT_CMD=… pytest tests/test_ocr_tesseract.py` | 6 passed against a real Tesseract 5.5.3 |
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
| The §11 incident PDF, replayed after the fixes | `extracted` on attempt 2 via live Gemini; 9 verified, 0 dropped, 9/9 spans resolve exactly; no NUL stored; the worker log carries ids and counts only (2026-08-07) |
| Progress stream against Postgres + ARQ + live Gemini | upload → `processing` → `extracted` → `done` on one connection; 10/10 claims verified, every match tier-1 exact (2026-08-07) |
| Progress stream through the retry policy | attempt 1 failed → attempt 2 failed → `dead_lettered`, each with its reason, at +0.6 s / +5.8 s / +16.1 s — the 5 s and 10 s backoffs, watched rather than inferred. `POST /retry` then reached `extracted` on attempt 4, 12/12 verified (2026-08-07) |
| **Browser, end to end** | upload a Thai PDF against live Gemini: the line under the form moves "Uploading…" → "Parsing and verifying evidence…" → 10/10 claims, and clicking a citation highlights it in the document pane. Then with the provider down: "Attempt 1 failed, retrying — …" → "Attempt 2 failed…" → "Stopped after 3 attempts" with the reason and the parsed text still shown; "Try again" reached `extracted` with 12/12 (2026-08-08) |
| OCR through the whole stack (Postgres + ARQ + live Gemini) | `resume_scanned.pdf`, previously a permanent `failed`, streamed `pending` → `processing` → `extracted` in 5.7 s with `pages_from_ocr=[1]`; 7/7 verified, 0 dropped, every match tier-1 exact, all 7 spans slicing back out of the stored text, no NUL. Three of the skills were cited out of the **Thai** OCR line `ทักษะ: Python, FastAPI, PostgreSQL` (2026-08-08) |
| OCR on a partial scan | `resume_mixed_scan.pdf` → `extracted` with `pages_from_ocr=[2]`: page 1 kept its text layer, page 2 came from the image, 5/5 verified and 5/5 spans exact (2026-08-08) |
| Migration `0003` on Postgres | `upgrade head` → `downgrade -1` → `upgrade head`; `pages_from_ocr` lands as real `jsonb` and `alembic check` finds no drift (2026-08-08) |
| **The whole stack in containers** | `docker compose up -d --build` from a clean daemon: seven services, `api` and `web` healthy, `migrate` exit 0. Against real Gemini — auth journey end to end (register → login → me → change-password → old password refused 401 → new one accepted → wrong current refused 403), `resume_th.pdf` 10/10 verified with 10/10 spans slicing back out of `document_text`, `resume_scanned.pdf` `extracted` with `pages_from_ocr=[1]` and 7/7 exact from the Tesseract *in the image*. Worker log shows arq taking the job; CORS preflight from :3000 passes; the web bundle carries `localhost:8000` and not `http://api:8000` (2026-08-08) |
| **Browser: a scan, end to end** | uploading `resume_scanned.pdf` at :3002 against live Gemini shows the amber banner "Page 1 had no text layer and was read by OCR. Quotes from it match what was recognized, which may differ from what was printed.", `7/7 claims verified`, and the document pane rendering the recognized text — six `<mark>` highlights over it, including two inside the Thai line, with the ambiguous `Python` in amber and the rest emerald (2026-08-08) |
| **Two columns, live** | `resume_two_column.pdf` through `app.cli` against Gemini: 7/7 verified, 0 dropped, **on attempt 1** — the first live run of this fixture needed the re-ask loop. `resume_two_column_header.pdf` 8/8, every match tier-1 exact (2026-08-08) |
| Single-column output is unchanged | every text-layer fixture parsed with column detection on and with it forced off: **byte-identical** in each case, and only the two two-column documents reordered, with the same words present (2026-08-08) |
| **MinIO, end to end in the containers** | `STORAGE_BACKEND=minio docker compose up -d --build` against real Gemini: upload answered `pending` in 22 ms, `resume_th.pdf` reached `extracted` in 10.2 s, 10/10 verified, 0 dropped, all matches exact, all 10 spans slicing back out of `document_text`. `mc ls` shows the object in `hirelens-resumes`; **nothing** was written to the uploads volume; the worker logs `storage=minio`; re-uploading the same bytes returned 200 on the same row with `attempts` still 1 (2026-08-08) |
| The OCR confidence gate, against the real binary | a clean `resume_scanned.pdf` scores 94.8 and passes; the same page at 6px blur scores 47.4 and is refused, where with the gate off it is accepted with "Somchai Jaidee" nowhere in the text (2026-08-08) |
| Migration `0004` on Postgres | `upgrade head` → `downgrade -1` → `upgrade head`; `alembic check` finds no drift, and the `weight > 0` check constraint refuses a bad row **on Postgres**, not only in the tests (2026-08-08) |
| **Jobs and requirements, live in the containers** | `api` and `worker` rebuilt first, and `/openapi.json` lists all four `/jobs` routes — the proof the container serves the code just written. Then: create a job with four requirements → read it back in order → a second account gets **404** → `weight: 0` gets **422**. Thai round-trips exactly (`ภาษาไทย`, 7 chars / 21 bytes read straight out of Postgres — the console's mangled rendering was PowerShell 5.1, not the data) (2026-08-08) |
| Migration `0005` on Postgres | `upgrade head` → `downgrade -1` → `upgrade head`; `page_spans` lands as real `jsonb` (checked in `psql`, not inferred) and `alembic check` finds no drift (2026-08-08) |
| **Judging, live against Gemini** | `resume_th.pdf` via `app.cli`: a Thai requirement typed as `ปริญญาตรีวิศวกรรมคอมพิวเตอร์` matched the document's own differently-worded `วิศวกรรมศาสตรบัณฑิต สาขาวิศวกรรมคอมพิวเตอร์`, while `ประสบการณ์ Backend อย่างน้อย 3 ปี` came back `not_evidenced` — the resume never states a total, and the never-infer rule held. `resume_en.pdf` 3/5 met on semantic requirements ("Bachelor's degree in engineering" → the Chulalongkorn line). 0 dropped, 0% hallucination rate, every match tier-1 exact, 1 attempt (2026-08-08) |
| **A judgment's pages come from the row, not a re-parse** | `resume_multipage.pdf` judged against a `ParsedDocument.from_stored` built from stored text + stored spans only: 2/2 met, cited on **pages 2 and 3**, every span slicing back out exactly. That is the screening path end to end, minus the row slice 3 adds (2026-08-08) |
| Judging's three decisions, mutation-tested | Reverting each in turn — extraction's "fewest dropped" rule, trusting the model's requirement numbering, and letting a claimed match set the verdict — fails 1, 3 and 4 cases of `test_judge.py` respectively. The tests defend the decisions rather than describing them (2026-08-08) |
| The CLI's old path is untouched | `python -m app.cli` over three fixtures, before and after `--requirement` was added: **identical**, 66 lines, timing masked (2026-08-08) |

### Repository state

`main` is on GitHub at <https://github.com/67160366/hirelens>. **M3 slice 1 is
pushed and green on CI** (run `31247527205`, 2026-08-08): 295 passed, 25 skipped on
a runner with no Tesseract, no database, no MinIO and no API key — the same numbers
as a local run, which is the opt-in test design doing its job — plus 9 vitest cases
in `web/`. The only annotations on that run come from inside `actions/setup-node`
itself (Node's `punycode` and `url.parse` deprecations); nothing in this repo emits
one.

**Slice 2's two commits are not yet pushed** — `page_spans` + migration `0005`, and
judging. Check `git rev-list --count origin/main..main` before assuming anything
here: a batch of verified-but-unpushed commits is the easiest way for local and CI
to drift apart, and CI is the only thing that tests a clean machine with no `.env`,
no Docker and no API key.

CI (`.github/workflows/ci.yml`) runs `ruff check`, `ruff format --check`,
`mypy app`, `pytest -q`, then `npm ci`/`typecheck`/`lint`/`build`. It has no
database, no Redis, no MinIO and no API key, which the next section explains.

**Read a green run's annotations, not just its tick.** `setup-uv` was bumped from
`@v5` to `@v6` to get off Node 20, CI went green, and the deprecation warning was
still there: `@v6` is the newest *floating* major tag, but the action stopped
publishing floating majors at v8 deliberately — a moving `@vN` is what made the
tj-actions supply-chain attack possible — so it is two majors stale and still targets
node20. It is pinned at `@v9.0.0` now. The general form of this: a version bump that
still emits the warning it was meant to remove has not worked.

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
| 4 | `api/app/pipeline/parse.py` | The offset contract: `ParsedDocument.text` is the single coordinate space all evidence points into. `layout.py` beside it decides *reading order* and is worth skimming for why it answers `None` so often |
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
    parse.py           PDF/DOCX → text + char offsets + page spans; scans vs blank
    layout.py          column detection; `None` means "read it the old way"
    ocr.py             OCREngine seam + Tesseract; recovers pages with no text layer,
                       and refuses one it read badly
    extract.py         orchestrates: ask → verify → re-ask → keep the cleanest result
    judge.py           M3: the same shape for requirements — the verdict is *derived*
                       from what resolved, never taken from the model
    prompts.py         versioned prompts (EXTRACTION_PROMPT_VERSION, JUDGMENT_…)
  llm/
    base.py            StructuredExtractor interface, error taxonomy, usage/cost types
    fake.py          ★ rule-based extractor over the real document + failure modes
    gemini.py          Gemini free tier via google-genai
    registry.py        provider selection from settings
  schemas/
    extraction.py      what the model returns — quotes only, no offsets
    profile.py         what we store — offsets, pages, stats, dropped claims
    judgment.py        M3: both layers for judging. RequirementSpec is a plain DTO,
                       so judge.py stays ORM-free the way extract.py is
  models/core.py       candidates, resumes, extracted_profiles, llm_call_logs
  models/matching.py   M3: jobs and the requirements they are screened by
  storage.py           LocalStorage / MinioStorage behind one interface
  services/resume_service.py   upload path: store, insert, queue; and process_resume
  jobs.py            ★ run_resume_job — the unit of background work and the retry policy
  queue.py             JobQueue seam: inline (no server) / arq (Redis)
  worker.py            `arq app.worker.WorkerSettings` — adapter only
  logging_config.py    shared by API and worker so the worker need not import the app
  api/routes/          auth.py, resumes.py — upload, profile, retry, progress stream
                       jobs.py — postings and requirements; requirement routes are
                       nested so ownership is settled in one place
  cli.py               `python -m app.cli <pdf>` — fastest way to see output
web/
  app/page.tsx         auth + upload + live progress + result + retry
  lib/api.ts           typed client; `waitForProfile` streams, then falls back to polling
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
- **The progress stream is the contract; polling the row is only the mechanism.**
  `GET /resumes/{id}/events` re-reads the resume on an interval and emits when it
  changes. The worker publishing to Redis would be a truer push, but it would put
  Redis on the API's critical path and break the no-server default that
  `QUEUE_BACKEND=inline` and the entire test suite rely on. Swapping the mechanism
  later changes nothing a client can see.
- **The web client streams with `fetch`, not `EventSource`.** `EventSource` cannot
  set an `Authorization` header, so the token would have to travel in the query
  string — into proxy access logs and browser history, in a project whose rules
  forbid logging personal data. The cost is parsing SSE frames by hand in
  `web/lib/api.ts`; the bearer header, the `ApiError` taxonomy and the 401-refresh
  path all keep working in exchange.
- **OCR runs before page spans are measured, not after.** `parse.py` substitutes the
  recognized text into the page list and only then calls `_assemble`, so a rescued
  page is indistinguishable from one that always had text: no evidence offset, page
  mapping or highlight had to change, and `document_text` is still stored verbatim.
  It is the same move as the NUL strip in §11 — clean the text before anything
  indexes into it. Doing OCR as a second pass over already-assembled text would have
  shifted every offset after the rescued page.
- **The OCR engine is `OCREngine | None`, and `None` means off.** A null-object
  engine would return `""` for a disabled engine and `""` for a page it read and
  found nothing on. The second is a real answer about the document and has to stay
  distinguishable from a configuration.
- **A missing language pack is refused at startup, not discovered per document.**
  `build_ocr_engine` runs `--list-langs` and checks every requested code. Without
  that, a Tesseract lacking `tha` would keep working for English and return noise
  for Thai — the failure mode this project can least afford, and the same class of
  silent corruption as a stale price table.
- **Column detection answers `None` whenever it is not sure, and `None` is the old
  code path.** `layout.detect_reading_order` returns crop boxes only for a page it
  is confident is multi-column; everything else falls through to the
  `page.extract_text()` call that ran before M2 #6, so a single-column document
  parses byte-identically and no citation already shown to a user can shift. Four
  guards exist to produce that `None`, and the reordering is done by *cropping* to a
  region and letting pdfplumber assemble the text — rebuilding lines from word boxes
  would mean re-deciding where spaces go, and Thai has no spaces between words.
- **The horizontal cut comes before the vertical one.** A full-width header line
  spans the gutter, so a column profile taken over the whole page finds nothing on
  almost every real two-column resume. Cutting into bands at wide row gaps first is
  what makes the header its own region and exposes the gutter underneath it.
- **Only a missing object may raise `ObjectNotFoundError`.** `is_retryable` reads
  that exception as permanent. Every other storage fault — a refused connection, a
  timeout, a 500 — is a plain `StorageError` and gets the retry budget. Backwards,
  a MinIO restart would permanently fail every resume uploaded during it.
- **A page OCR read badly is refused, not reported.** A character count cannot tell
  text from noise, so `OCR_MIN_CONFIDENCE` reads Tesseract's own per-word confidence
  and returns `""` for a page below it — deliberately the same answer as "I read
  this and found nothing", so it reuses a path that already exists and already says
  the right thing to the user. The threshold is measured (§7), and the TSV pass that
  produces it is a *second* invocation because TSV tokenizes Thai per glyph and
  cannot supply the text.
- **A judgment has no `not_met`, on purpose** (M3). The model is asked only for
  quotes showing a requirement *is* met, and the verdict is derived from what
  `EvidenceResolver` could locate: `met` if a quote resolved, `not_evidenced` if
  none did. Absence cannot be quoted — you cannot cite text that is not in the
  document — so a "not met" verdict would be exactly the unverifiable assertion this
  project exists to refuse. It is also the honest label: the system cannot tell "the
  candidate lacks it" from "the resume does not mention it", and one of those is a
  statement about a person.
- **Judging's retry loop keeps the most *met*, not the fewest dropped** (M3 slice 2).
  `extract_profile` keeps the attempt with the fewest rejections, which is right for
  a profile because every field is independent. It is wrong for judging: the retry
  prompt tells the model to leave a requirement out rather than reword a rejected
  quote, so a compliant second attempt can answer about nothing at all and score zero
  rejections — and on extraction's rule that empty answer wins, silently discarding
  requirements the first attempt had proven with real citations. `_is_better` in
  `pipeline/judge.py` prefers more `met`, then fewer dropped. Mutation-tested: swap it
  for extraction's rule and `test_judge.py` fails.
- **A model refers to a requirement by number, and a bad number is a fabrication**
  (M3 slice 2). 1-based index rather than UUID: far cheaper in tokens, and unlike a
  garbled UUID an out-of-range integer is something the verifier can catch. It lands
  in `dropped` as `RejectReason.UNKNOWN_REQUIREMENT` — pointing at a requirement that
  does not exist is the same class of claim as quoting text that is not there, so it
  belongs in the same counter. Duplicate numbers **merge** rather than overwrite,
  because a model splitting one requirement's answer across two entries has still
  answered, and dropping the second would lose verifiable evidence in silence.
- **The requirement list sits outside `<resume>` in the prompt** (M3 slice 2). Not
  cosmetic: `app/llm/fake.py` locates the document by that exact block, so a list
  inside it would be quoted as though it were the resume and every quote would fail
  verification. It also matches what the model is told — a requirement's own wording
  is never evidence that a candidate meets it, and `test_judge.py` pins that.
- **A requirement is an input, not a claim, so it needs no evidence** (M3).
  Requirements are typed in through CRUD rather than decomposed out of a pasted job
  description by a model. Nothing here is a statement about a candidate, so the
  guardrail has nothing to check — and a model in front of this step would add a
  failure mode without adding a guarantee. The description is stored beside them for
  context and audit, and is deliberately *not* what anyone is judged against:
  judging free text makes it impossible to say which part of a posting a verdict
  answered.
- **A job is owned by a `Candidate` row.** That is the only actor the system has,
  and RBAC is M4's. The M3 rule is therefore "you may screen a resume you own
  against a job you own", which M4 widens without changing the table.
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
| `failed` | **This document cannot be processed.** A corrupt file, a blank one, a missing object, a missing API key — or a scan that OCR was not enabled for, or could not read. Retrying changes nothing *unless the configuration changes*, which is why `POST /retry` accepts it. |
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

- **Column detection is conservative on purpose, and will miss layouts.** It refuses
  anything it is not confident about, so a two-column resume with an unusually narrow
  gutter, or one whose columns are wildly unequal in size, still reads interleaved —
  as it always did. That direction is deliberate: a page wrongly split reorders text
  that was fine, and there is no test in this repo that would notice. The four guards
  and the numbers behind them are in `app/pipeline/layout.py`; `tests/test_layout.py`
  pins each one separately, because a guard that quietly stops firing is the failure
  this module is least able to see.
  *(The strict xfail that used to live here started passing on 2026-08-08 and failed
  the suite, which is exactly what it was for. The characterization test beside it is
  deleted and the marker is off; `test_columns_should_read_one_after_the_other`
  survives as an ordinary test under the same name.)*
- **`registry.py` raises for `LLM_PROVIDER=anthropic`** on purpose. An adapter never
  run against the real API is worse than an honest error.
- **An OCR'd citation is faithful to what was read, not to what was printed.** The
  recognized text *becomes* `document_text`, so the guardrail is untouched — a quote
  is still checked against exactly what the model was shown, and a fabrication is
  still dropped. What OCR cannot promise is that it read the page correctly, so a
  citation can faithfully quote a misrecognition. `pages_from_ocr` names those pages
  and the UI says so. The fixtures OCR perfectly because they are clean synthetic
  renders; a photographed resume will not, and no test in this repo can show that.
- **No image preprocessing before OCR** — no deskew, threshold or upscale, just a
  300 dpi render. That was a guess when it was written; it was then measured
  (2026-08-08) by degrading `resume_scanned.pdf` sixteen ways and scoring how many
  known lines still resolve as evidence:

  | Degradation | Where it stops working |
  |---|---|
  | **Rotation** | 2° is perfect, 5° loses one line, 8° collapses to 1/5, 12°+ raises `NoTextLayerError` |
  | **Blur** | fine to 3.0px, 2/5 at 4.5px, 0/5 at 6.0px |
  | **Resolution** | fine down to ¼, 3/5 at ⅙, 0/5 at ⅛ |
  | Contrast, brightness, JPEG (even q3), speckle | **no measurable effect** |

  So preprocessing stays out, with one exception worth knowing: **skew is the only
  cliff that is both steep and common** — a phone photo of a resume is rotated far
  more often than it is blurred. A deskew step is the one preprocessing item with
  evidence behind it.
- **A badly degraded scan used to fail by producing confident nonsense** — at 6px
  blur the page still yields 160+ characters, far above `MIN_CHARS_PER_TEXT_PAGE`, so
  it was accepted as readable while "Somchai Jaidee" had become "Sore hector".
  **Closed on 2026-08-08** by `OCR_MIN_CONFIDENCE`, which reads Tesseract's per-word
  confidence and refuses the page. The threshold was measured, not guessed — rerun
  `python tests/tools/ocr_degradation.py --tesseract <path>` to reproduce the table:

  | Degradation | lines found | mean confidence |
  |---|---|---|
  | clean | 5/5 | **94.8** |
  | rotate 2° / 5° | 4/5 | 94.2 / 91.5 |
  | rotate 8° / 12° | 2/5 / 0/5 | 72.4 / 0.0 |
  | blur 1.5px / 3.0px | 5/5 | 94.8 / 94.5 |
  | blur 4.5px / 6.0px | 2/5 / 0/5 | 83.6 / **47.4** |
  | scale ½ / ¼ | 5/5 | 94.8 / **90.2** |
  | scale ⅙ / ⅛ | 2/5 / 0/5 | 57.9 / 46.9 |
  | contrast 0.4, JPEG q3 | 5/5 | 94.8 |

  Everything that still yielded the fixture's content scored **90.2 or better**;
  everything that yielded none scored **47.4 or worse**. The default 75 sits in that
  gap and low in it on purpose: these are clean synthetic renders, and a real
  photograph will score lower while still being readable. A wrongly refused scan is a
  message the user can act on; a wrongly accepted one is a confident, fully cited
  profile of the wrong words. **What is still true:** the gate is tuned on one
  synthetic fixture, and blur 4.5px (83.6, 2/5 lines) still gets through.
- **A `.docx` citation says "page 1" because a `.docx` has no pages.** Word decides
  where a page breaks when it renders, so the file does not contain the answer.
  Reporting the whole document as one page is the honest version; author-inserted
  page breaks *are* in the file and could split it later, but automatic ones never
  will be.
- **An image-only `.docx` is reported blank, not scanned.** OCR here reads pages
  rendered from a PDF; images embedded in a Word file are not run through it, and
  calling one a scan would send the user after a setting that would not help.
- **Ambiguous citations are flagged, not resolved.** A quote like `Python` appearing
  in both a bullet and a skills list is reported ambiguous rather than guessed.
  A worthwhile refinement is to prefer the skills-section span for skill claims.
- **`_reference` is duplicated between `extract.py` and `judge.py`** — the ~15 lines
  that resolve a quote and record the outcome either way. A shared home would have to
  import both `pipeline.evidence` and `schemas.profile`, and `schemas.profile` already
  imports `evidence`, so it needs a new module rather than a function moved into an
  existing one. Deliberately deferred: extracting it means editing `extract.py`, the
  most load-bearing file after `evidence.py`, in the same milestone that already has
  to pull `decide_retry` out of `jobs.py`. Worth doing when something wants it a third
  time.
- **Judging never sees `must_have` or `weight`, and that is the point.** They travel
  on `RequirementSpec` and come back on `RequirementJudgment` untouched, for ranking
  (slice 4) to read. Whether a requirement is evidenced is a question about the
  document; how much it matters is a question about the job. A judge that consulted
  the weight would be scoring, which is the thing this milestone refuses to become.
- **A resume stuck at `processing` is never reaped.** If a worker dies mid-job
  nothing sweeps the row back to `pending`; the job that redelivers it will skip it
  as already claimed. A visibility timeout on `last_attempt_at` would fix it and
  belongs with M5's observability work.
- **The client still knows how to poll.** `api.waitForProfile` opens the stream
  first and falls back to the old loop when the stream ends without a verdict — a
  proxy that buffers `text/event-stream`, or a connection the server capped. It is
  still deliberately the one place that waits. Deleting the fallback would trade a
  working page for a purer one.
- **A change that does not outlive `SSE_POLL_SECONDS` is not streamed.** The
  endpoint re-reads the row twice a second by default, so a `processing` that lasts
  20 ms — a job failing instantly against a provider that is down — is over before
  the next read. Every *resting* state and every `failure_reason` still arrives,
  which is what a client acts on; only the flicker is lost. Pub/sub would close the
  gap, and §5 says why it is not there yet.
- **A stream capped at `SSE_MAX_STREAM_SECONDS` is not a failure.** It is how a
  resume stranded at `processing` by a dead worker (below) stops holding a
  connection open. The client polls on from there, and sees the same nothing —
  which is the honest answer until the reaper lands with M5.
- **Enums are stored as their *names*** (`EXTRACTED`, `DEAD_LETTERED`, `LANGUAGE`),
  because SQLAlchemy's `Enum` persists names by default, while the API serializes
  the values (`extracted`, `language`). Harmless, and worth knowing before writing a
  raw SQL query against `resumes.status` or `job_requirements.kind` — a
  `WHERE kind = 'language'` returns zero rows against data you just watched go in.
  Migration `0001` lists the lower-case values for `resumestatus`, which is
  misleading but inert: `native_enum=False` emits no CHECK constraint for them to
  disagree with. `0004` declares the upper-case forms instead, which is the shape to
  copy from here on.

---

## 8. Environment — read before running anything

**The project path must stay ASCII.** This machine's ANSI codepage is **cp874
(Thai)**. The project originally lived at `D:\งาน\webapp_dev`, and an editable
install (`uv pip install -e .`) wrote a `.pth` file containing that path in UTF-8.
Python's `site` module reads `.pth` files using the system codepage, hit byte
`0x87`, and the interpreter died at startup — the venv became unusable. The project
was moved to `D:\work\webapp_dev` and the problem is gone. Do not move it back
under a non-ASCII path, and prefer ASCII paths for anything Docker bind-mounts.

**Binary fixtures must stay binary.** `core.autocrlf=true` is the Git-for-Windows
default, and until 2026-08-08 this repo had no `.gitattributes`. Git guessed the PDF
fixtures were text and rewrote `0x0A` inside their compressed streams on checkout,
so `resume_scanned.pdf` arrived 35293 bytes instead of 35214, its xref offsets no
longer pointed anywhere real, and `test_image_only_pdf_reports_a_scan` failed on a
clone where nothing was wrong with the code. That made "`git clone && pytest -q`
works" false on a default Windows install. `.gitattributes` now marks `*.pdf`,
`*.docx` and the image types `binary` — **do not remove those lines, and add a line
for any new binary fixture type**.

If you ever suspect this has happened, **compare file sizes, not hashes**:
`git hash-object` re-normalizes while hashing and will report a corrupted file as
identical to the blob.

`api/pyproject.toml` sets `pythonpath = ["."]` for pytest, so the suite works
without an editable install at all.

### Current state of the local stack

| Thing | State |
|---|---|
| Docker | **Installed and running.** `docker compose up -d --build` brings up the *whole system*: `postgres` (pgvector/pg17), `redis`, `minio`, the one-shot `migrate` and `createbucket`, plus `api`, `worker` and `web` from two locally built images. Docker Desktop lives at `%LOCALAPPDATA%\Programs\DockerDesktop\Docker Desktop.exe` — a per-user install, *not* under `Program Files`. |
| Database | **Postgres** in Docker (`.env` → `DATABASE_URL`), migrated and verified 2026-08-07. SQLite at `api/var/dev.db` is a commented fallback. The test suite uses its own in-memory SQLite. |
| Test database | `hirelens_test`, created by hand. Only `tests/test_postgres.py` uses it, and it refuses to run against the dev database because it drops every table. |
| Queue | **`arq`** (`.env` → `QUEUE_BACKEND`). Needs `arq app.worker.WorkerSettings` running. `inline` processes in-request with no Redis. |
| LLM provider | **`gemini`** (`gemini-3.6-flash`) in `.env`; live-verified against every fixture on 2026-08-06 — `docs/llm-providers.md`. Tests and CI run on `fake`. |
| Storage | **Local filesystem** at `var/uploads` by default. `STORAGE_BACKEND=minio` switches the API and the worker to the MinIO in compose, which creates its bucket in a `createbucket` one-shot; a missing bucket is refused at startup. Verified end to end on 2026-08-08 (§1). Opt-in tests need `TEST_MINIO_ENDPOINT`. |
| OCR | **Tesseract 5.5.3** installed 2026-08-08, with `eng`, `tha` and `osd`. A *portable* install at `C:\Users\golfv\tesseract.exe` (tessdata beside it), so it is **not on PATH** — `OCR_COMMAND` must carry the full path. Off by default; tests and CI run without it. A recognized page below `OCR_MIN_CONFIDENCE` (default 75) is refused rather than reported — §7 has the measurements. |

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
| `test_parse.py` | Offsets, page spans, scan detection, two-column reading order, and the PDF that is broken on purpose |
| `test_layout.py` | Column detection: every guard that produces `None`, separately, plus the band merge |
| `test_storage.py` | The storage contract on `LocalStorage`, and the MinIO error mapping the retry policy depends on — stubbed, so it runs everywhere |
| `test_minio.py` | The same contract against a real object store. **Opt-in**, needs `TEST_MINIO_ENDPOINT` |
| `test_docx.py` | Paragraphs, tables, document order, and that a page-less format is not given invented page numbers |
| `test_ocr.py` | The OCR fallback through a stub engine: which pages are chosen, the offset contract across a rescued page, and what happens when recognition finds nothing |
| `test_ocr_tesseract.py` | The real binary, including Thai and the confidence gate's actual numbers. **Opt-in**, needs `OCR_TESSERACT_CMD` |
| `test_extract.py` | The re-ask loop and how it picks a result |
| `test_llm.py` / `test_gemini.py` | The provider seam; Gemini's contract via mocks |
| `test_api.py` | Auth, upload gates, reading a profile back |
| `test_resume_service.py` | The duplicate-upload race, blob cleanup, PII-safe logging |
| `test_worker.py` | Upload enqueues; the job runs; the arq adapter |
| `test_retry.py` | Error classification, backoff, dead-lettering, replay |
| `test_events.py` | The progress stream: ownership, the frame sequence, the cap, keep-alives |
| `test_postgres.py` | JSONB, Thai round-trip, JSON queries. **Opt-in**, needs `TEST_DATABASE_URL` |
| `test_config.py` | Settings validation, including the JWT-secret refusal |

---

## 9. Next steps

**All setup items are done, and M2 is closed.** Docker is installed, development
runs on Postgres, the JSONB path is verified, Gemini has run live, the queue is
real, and every M2 item below is shipped and verified against a running system.

**M3 is under way and its scope is settled** — reviewed with the owner on
2026-08-08, so `docs/PLAN.md` now holds commitments rather than a reconstruction.
The two questions the previous handoff said to decide early are both answered: a
requirement is a row carrying `kind`, `label`, `detail`, `must_have` and `weight`
(`app/models/matching.py`), and judging reuses `EvidenceResolver` **unchanged**,
along with `EvidenceRef`, `DroppedClaim` and `EvidenceStats` from
`schemas/profile.py` — which is what makes the hallucination rate cover judging for
free.

| # | Work | Status |
|---|---|---|
| 1 | Jobs and requirements as rows, with CRUD | **done** — `models/matching.py`, `api/routes/jobs.py`, migration `0004`, `tests/test_jobs.py` |
| 2 | Requirement-level judging | **done** — `pipeline/judge.py` + `schemas/judgment.py`, `page_spans` + migration `0005`, `fake.py` teaching, `--requirement` on the CLI, `tests/test_judge.py` |
| 3 | Screening as a row, on the background worker | next — shares the retry policy via a pure `decide_retry` extracted from `app/jobs.py` |
| 4 | Ranking across candidates | a pure function, no model; must-haves gate, citations are the rationale |
| 5 | A thin web UI | job authoring, verdicts, citation highlighting through the existing `DocumentPane` |
| 6 | Retrieval — the pre-filter | `Retriever` seam; lexical default, pgvector opt-in |

**Four things to know before starting slice 3:**

1. **`judge_requirements` is pure and takes no ORM.** It wants a `ParsedDocument`, a
   `list[RequirementSpec]` and an extractor. Slice 3 builds the document with
   `ParsedDocument.from_stored(resume.document_text, resume.page_spans)` — never
   `reparse_document`, which reads the file again and can shift offsets — and the
   specs from `JobRequirement` rows. That seam is why `tests/test_judge.py` needs no
   database.
2. **The screening row needs its own `prompt_version`.** `LLMCallLog.prompt_version`
   is written with `EXTRACTION_PROMPT_VERSION` today; a judging call must record
   `JUDGMENT_PROMPT_VERSION` or the two prompt families become indistinguishable in
   the cost table. `LLMCallLog.resume_id` also assumes a resume — a screening's calls
   need somewhere to hang.
3. **`requirements_hash` has to cover what the judge actually saw.** The prompt
   carries `kind`, `label` and `detail` **and their order**, so a reorder changes the
   result and must change the hash. `must_have` and `weight` do not reach the judge
   at all — they are ranking's inputs — so a change to either should stale a
   *ranking*, not a screening.
4. **One model call per screening, carrying the whole `document_text`** — not one
   call per requirement. Requirement count × resume count is this milestone's cost
   multiplier, and slice 6 exists to keep the resume side of that product small.

M2, for the record — nothing in it is outstanding (live status in `docs/PLAN.md`):

| # | Work | Notes |
|---|---|---|
| 1 | ~~ARQ worker + Redis~~ **done** | `app/jobs.py` (work), `app/queue.py` (seam), `app/worker.py` (entrypoint) |
| 2 | ~~Job state, retry with backoff, dead-letter queue~~ **done** | §6 above |
| 3 | ~~SSE progress endpoint~~ **done** | `GET /resumes/{id}/events` (`api/app/api/routes/resumes.py`), consumed by `waitForProfile` in `web/lib/api.ts`, which keeps polling as the fallback. Pinned by `api/tests/test_events.py` |
| 4 | ~~OCR fallback for scans~~ **done** | `app/pipeline/ocr.py` is the seam; `parse.py` substitutes recognized text before spans are measured. Off by default (`OCR_ENGINE=none`), so CI and a fresh clone are unchanged. Pinned by `tests/test_ocr.py` (stub engine) plus the opt-in `tests/test_ocr_tesseract.py` |
| 5 | ~~DOCX parser~~ **done** | `parse_docx` in `parse.py` reads paragraphs and tables in document order; a `.docx` has no pages so it is reported as one. The upload gate keeps a magic-byte signature per type. Pinned by `tests/test_docx.py` |
| 6 | ~~Two-column fix~~ **done** | `app/pipeline/layout.py` — a bounded XY-cut. `None` for anything it is unsure of, which is the pre-M2 code path, so single-column output is byte-identical. Pinned by `tests/test_layout.py` |
| 7 | ~~MinIO storage backend~~ **done** | `MinioStorage` in `app/storage.py`; the API and the worker build storage independently so both pick it up. The contract in `tests/storage_contract.py` runs against both backends |
| 8 | ~~Evidence viewer~~ **done** — text-layer only | `web/components/DocumentPane.tsx` highlights every citation in `document_text` and scrolls to the one clicked. A true pdf.js overlay is still not done, but #6 now extracts the bbox geometry it needs, so what remains is an endpoint serving the original file and a pdf.js canvas — a frontend slice, parked with M5's recruiter UI |

The browser walkthrough was re-done on 2026-08-08 and covered the whole journey
including the retry path (§1); the OCR banner was checked in a real browser once
`CORS_ORIGINS` became a setting and unblocked running the dev server on a free port.

Two things landed alongside M2 and are recorded in `docs/NOTES.md`: the stack was
containerized (M5's "containerize API + web", pulled forward for a course
deliverable) and `POST /auth/change-password` shipped.

**Still true, and still worth not renegotiating:**

- **The browser has not seen the two-column or MinIO work.** Both are verified at
  the HTTP level and in the containers, but no one has watched a two-column resume
  render in `DocumentPane`. Still the cheapest outstanding check, and M3 slice 5 is
  the natural moment to fold it in.
- **M4–M6 in `docs/PLAN.md` are still a draft** reconstructed from the README. M3 is
  not any more — review each of the others the same way before building to it.
- **The scope lines hold**: the baseline-ranking evaluation stays in M6 with its
  one-week timebox, and `LLM_PROVIDER=anthropic` stays an error until a live
  verification run.

M4 onward (backend depth, frontend, ship) is in [`docs/PLAN.md`](PLAN.md), which
also tracks the status of every item above.

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
- **`pytest -q` cannot see a migration.** The suite builds its tables with
  `create_all` on SQLite, so a migration can be wrong in ways every test is blind
  to. A new table is not verified until it has round-tripped on real Postgres
  (`upgrade head` → `downgrade -1` → `upgrade head`), `alembic check` reports no
  drift, and you have queried it there. Both of migration `0004`'s defects were
  invisible to a green suite.
- **In a migration, name a check constraint with the bare name.** `ck` is the only
  convention in `models/base.py` that interpolates `%(constraint_name)s`, so
  `name="ck_<table>_<rule>"` gets wrapped a second time and `alembic check` reports
  drift against the model forever. `fk`, `pk` and `uq` names are safe spelled out —
  their conventions never reference the given name.
- **When a check says something surprising, suspect the instrument first.** Three
  tools have now each told a confident lie here: `git hash-object` reported
  CRLF-corrupted PDFs as intact because it normalizes while hashing, a
  `WHERE kind = 'language'` query returned nothing because SQLAlchemy stores enum
  *names*, and PowerShell 5.1 rendered stored Thai as mojibake because it decodes a
  JSON body as Latin-1 when the server names no charset. In each case the data was
  fine and the question was wrong. Go to the store that cannot lie — `psql`, and
  byte counts rather than eyeballs.
- **Before believing a live run, prove you are testing what you built.** Three things
  have each caused a wrong conclusion here: a zombie server on the old port serving
  old code, a *second* ARQ worker left running from an earlier session quietly taking
  the job (2026-08-08 — the giveaway was the old wording in `failure_reason`), and a
  dev server on a port the API's CORS list did not allow. Check the route exists
  (`curl /openapi.json | grep <new-field>`) and that nothing else is polling the
  queue.
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

## 11. The three defects one real PDF exposed — fixed 2026-08-07

Found by uploading a real-world Thai resume template (a designer-tool PDF,
443 KB, 1 page) through the browser against Postgres + the ARQ worker + live
Gemini, and fixed the same day. The incident: the pipeline succeeded completely
— parse, two Gemini calls, every claim verified — then the **commit** failed on
a NUL in `document_text`, the transaction rolled back, the resume stranded at
`processing`, and the database error carried the resume's text into the log.
One incident, three independent defects:

| # | Defect | Fix |
|---|---|---|
| 1 | `pdfplumber` returns `U+0000` for glyphs whose embedded font has no usable ToUnicode mapping (8 of them in this PDF — Thai tone marks). Postgres refuses NUL in a text column; SQLite stores it, so the whole suite was blind. | `_assemble` strips `U+0000` at the point that already NFC-normalizes, *before* page spans are measured, so no offsets shift (`api/app/pipeline/parse.py`). Not a violation of the verbatim-`document_text` rule, which forbids touching text already **stored**, not cleaning at parse time. |
| 2 | The success commit in `run_resume_job` sat outside the retry policy's `try`. A failing commit escaped to arq with no bookkeeping, stranding the resume at `processing` — where redelivery skips it, `POST /retry` answers 409, and re-upload dedupes without re-queueing. | The commit moved inside the `try`; a persistence failure now goes through `_record_failure_on_a_fresh_session` like any other unexpected error and ends at `pending`/`dead_lettered` (`api/app/jobs.py`). |
| 3 | SQLAlchemy's `DBAPIError` string embeds statement parameters — `document_text` included — so resume text reached the worker log, and once bug 2 was fixed would have flowed into `failure_reason` and out through the API. | Unexpected errors are recorded and logged as their **type name only** (`_describe` in `api/app/jobs.py`); only `LLMError` and `ParseError`, whose messages this codebase writes, are quoted verbatim. `ObjectNotFoundError` is excluded too — its message carries the storage key. |

Pinned by: `TestControlCharacters` in `tests/test_parse.py` (NUL stripped,
offsets measured after the strip), `TestAFailingCommit` in `tests/test_retry.py`
(a failing commit retries, dead-letters, and never quotes the statement in the
reason or the log), and `test_text_from_broken_glyphs_round_trips` in the opt-in
`tests/test_postgres.py` (parser output survives the dialect that rejected it).

Verified end to end: the stranded row was reset by hand and replayed through the
fixed worker against live Gemini — `extracted` on attempt 2, 9 verified, 0
dropped, all 9 spans resolving exactly against the stored text (1743 chars; the
8 NULs gone), and the worker log carrying ids and counts only.

One follow-up closed, one still open:

- ~~**A deliberately malformed fixture** alongside the clean ones.~~ **Done
  2026-08-08**: `resume_broken_tounicode.pdf` is a PDF whose font map is well-formed
  and says several glyphs mean U+0000, so pdfplumber emits real NUL and the road to
  the `_assemble` seam is covered by a real file. Two findings from building it:
  *removing* the `/ToUnicode` reference does **not** reproduce this — pdfminer falls
  back to `(cid:N)` placeholders, a different defect — so the damage has to be inside
  the map; and the fixture is therefore written by hand rather than by reportlab,
  which only ever writes correct maps. It is the one fixture that needs no Thai font
  to regenerate. The wider lesson still stands for *other* damage classes: mixed
  encodings, broken xrefs and real photographs are still unrepresented.
- **The visibility timeout from §7.** Bug 2's fix covers a commit that *fails*;
  a worker that dies mid-job (power loss, kill) can still strand a row at
  `processing`. That reaper belongs with M5's observability work, and is now the
  last open item from this incident.
