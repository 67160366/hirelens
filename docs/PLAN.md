# Milestone plan

The working plan for HireLens, kept in the repository so any session — human or
agent — can see where the project is and what comes next. Update the status
column and checklists as work lands; refresh `docs/HANDOFF.md` when a milestone
completes.

M1–M2 reflect decisions already made and verified, and so do **M3** and **M4** —
their scopes were reviewed with the owner (M3 on 2026-08-08, M4 on 2026-08-12), so
the decisions and slices below are commitments rather than a reconstruction.
**M5–M6 are still a draft** reconstructed from the README milestone table and HANDOFF
scope notes — review each of them the same way before treating the details as
commitments.

| Milestone | Scope | Status |
|---|---|---|
| M1 | Parse (PDF, offsets, Thai), extract, verify evidence, retry, auth, upload API, web UI | ✅ done (2026-07-30) |
| M2 | Async worker + queue, OCR, DOCX, two-column fix, MinIO, PDF viewer overlay | ✅ done (2026-08-08) |
| M3 | Job requirements, hybrid retrieval, requirement-level judging, ranking | ✅ done (2026-08-12) |
| M4 | Visibility timeout, RBAC, the application state machine, PDPA | in progress (scoped 2026-08-12) |
| M5 | Full recruiter UI, observability, deploy | draft |
| M6 | Optional: ranking evaluation vs BM25/embedding baseline — **one-week timebox** | draft |

---

## Setup items (before / alongside early M2)

- [x] **Docker Desktop installed; development moved onto Postgres** (2026-08-07).
  The compose stack runs (`postgres` + `redis` + `minio` all healthy), `.env`
  points at `postgresql+asyncpg://…`, and the initial migration round-trips
  (`upgrade head` → `downgrade base` → `upgrade head`) on real Postgres with
  `alembic check` reporting no drift. `profile` and `pages_without_text` land as
  real `jsonb`. The JSONB path is now pinned by `api/tests/test_postgres.py`,
  skipped unless `TEST_DATABASE_URL` is set so `pytest -q` and CI stay DB-free.
  End-to-end re-verified against Postgres: a Thai resume uploads, every one of
  its 10 citations still resolves against the stored `document_text`, and
  re-uploading the same bytes returns 200 from the Postgres unique constraint.
- [x] Gemini API key obtained (slot filled in `.env`).
- [x] **First live Gemini run** (2026-08-06) over every fixture via
  `python -m app.cli` — results and the two adapter fixes it forced
  (`gemini-2.5-flash` is 404 for new keys → `gemini-3.6-flash`;
  `response_schema` → `response_json_schema`) are recorded in
  `docs/llm-providers.md`. Headline: 0% final hallucination rate, every match
  tier-1 exact including Thai; the two-column fixture needed the retry loop.

## Blocking bugs — before any further M2 work

- [x] **Three defects from one real-world PDF** (found and fixed 2026-08-07),
  write-up in `docs/HANDOFF.md` §11. NUL is stripped in `_assemble` before page
  spans are measured; the success commit moved inside the retry policy's `try`,
  so a persistence failure retries and dead-letters instead of stranding the row
  at `processing`; and unexpected errors are recorded by type name only, so a
  database error can no longer carry `document_text` into the log,
  `failure_reason` or the API. Pinned by `TestControlCharacters` (parse),
  `TestAFailingCommit` (retry) and a NUL round-trip in `tests/test_postgres.py`.
  The stranded row was reset and replayed to `extracted` against live Gemini —
  9/9 citations resolve against the stored text.

## M2 — in dependency order (from HANDOFF §7)

- [x] 1. **ARQ worker + Redis; `process_resume` moved off the request**
  (2026-08-07). `app/jobs.py` holds the work (arq-free, so it is testable without
  Redis), `app/queue.py` is the `JobQueue` seam — `inline` for a server-free clone
  and the test suite, `arq` for the real thing — and `app/worker.py` is the
  `arq app.worker.WorkerSettings` entrypoint. Upload now stores, queues and
  answers `pending` in ~80 ms; the client polls until the status settles. Enqueue
  happens after the commit, and uses a job id derived from the resume id so a
  duplicate upload cannot queue the same work twice. Verified live against Redis,
  Postgres and real Gemini, including that a job queued while the worker was down
  is picked up when it restarts.
- [x] 2. **Job state, retry with backoff, dead-letter queue** (2026-08-07).
  `resumes` gained `attempts` (monotonic — it also makes each dispatch's queue job
  id unique, so a replay is not refused as a duplicate), `failed_attempts` (the
  retry budget, cleared by a success or a manual retry) and `last_attempt_at`;
  `ResumeStatus` gained `processing` and `dead_lettered`. `is_retryable` in
  `app/jobs.py` treats a broken document, a missing file and a missing API key as
  permanent and everything else as transient, so an unrecognised failure is
  retried rather than written off. Backoff is 5s, 10s, 20s. The job returns a
  decision instead of raising arq's `Retry`, which keeps the policy testable
  without Redis. `POST /resumes/{id}/retry` is the replay path — a dead letter
  nobody can run again is just a status. Verified live: 5s → 10s → dead-lettered
  against a downed provider, then replayed to a verified profile on attempt 4,
  reusing the text parsed before the first failure.
- [x] 3. **SSE progress endpoint; the web UI's waiting state wired to it**
  (2026-08-07). `GET /resumes/{id}/events` sends the resume's state on connect and
  again on every change, then `done` once it settles — replacing a re-fetch of
  `GET /resumes/{id}` every 700 ms, an authentication per tick, and a waiting
  message that could not tell "queued" apart from "attempt 1 failed, retrying".
  The endpoint re-reads the row on an interval rather than subscribing to Redis:
  the stream is the contract and the mechanism behind it can be replaced, while
  putting Redis on the API's critical path would break the no-server default the
  inline queue and the whole test suite depend on. The client uses `fetch` and a
  `ReadableStream` rather than `EventSource`, which cannot carry an
  `Authorization` header — the only alternative is a token in the query string,
  and so in proxy access logs and browser history. Polling survives as the
  fallback for a proxy that buffers `text/event-stream` or a connection the
  server caps.
- [x] 4. **OCR fallback for scans** (Tesseract + `tha`) (2026-08-08). A page with no
  text layer is rendered and recognized, and the text is substituted into the page
  list *before* `_assemble` measures spans — the same trick as the NUL strip, so no
  evidence offset, page mapping or highlight shifts, and a rescued page is
  indistinguishable from one that always had text. `app/pipeline/ocr.py` is the seam:
  an `OCREngine` ABC, a `TesseractEngine` driven over stdin/stdout (no new Python
  dependency, and the page image never touches disk — it is PII), and
  `build_ocr_engine`, which probes the binary *and its language packs* at startup,
  because a missing `tha` would leave English working while Thai came back as noise.
  Off by default (`OCR_ENGINE=none`) for the reason the extractor defaults to `fake`:
  Tesseract is a system binary and CI will never have one. The suite drives the whole
  path through a stub; `tests/test_ocr_tesseract.py` is opt-in on `OCR_TESSERACT_CMD`,
  mirroring `tests/test_postgres.py`. `pages_from_ocr` is recorded on the resume and
  surfaced in the UI, because a citation into an OCR'd page is faithful to what was
  read rather than to what was printed. Verified live against Postgres + ARQ + real
  Gemini: `resume_scanned.pdf` went from a permanent `failed` to `extracted` with 7/7
  claims verified, including three skills cited out of the **Thai** OCR line.
- [x] 5. **DOCX parser** (2026-08-08). `parse_docx` reads paragraphs *and tables* in
  document order — `document.paragraphs` skips anything inside a table, and resumes
  routinely put their skills in one, so the loss would have looked like a model that
  missed them rather than a parser that never saw them. A `.docx` has no pages (Word
  decides where page 2 falls at render time), so the whole document is reported as
  one page rather than having page numbers invented for it. The upload gate now
  keeps a signature per accepted type — `%PDF-` and the zip `PK\x03\x04` — so a
  relabelled file is still refused before it is stored or billed. Pinned by
  `tests/test_docx.py`; verified end to end with `python -m app.cli`: 7/7 verified,
  every match exact, Thai and table cells cited.
- [x] 6. **Two-column fix via bbox column detection** (2026-08-08).
  `app/pipeline/layout.py` does a bounded XY-cut: cut horizontally at wide row gaps
  *first* — a full-width header line spans the gutter and hides it from any profile
  taken over the whole page, which is why the obvious column-profile approach fails
  on almost every real two-column resume — then find a gutter inside each band, then
  re-merge adjacent two-column bands that share one so the body is not read left,
  right, left, right. Regions are extracted by cropping and letting pdfplumber
  assemble the text; rebuilding lines from word boxes would mean re-deciding where
  spaces go, and Thai has no spaces between words. The load-bearing property is that
  `detect_reading_order` returns `None` for anything it is not confident about, so
  the pre-M2 code path runs and a single-column document parses **byte-identically**
  — verified across every fixture, with only the two two-column documents reordered.
  Four guards produce that `None`; the fourth (a gutter must be narrower than the
  text beside it) came from the fixture written to catch the realistic false
  positive, a resume with its dates right-aligned at the margin. The strict xfail
  started passing and failed the suite, which is what it was for: the paired
  characterization test is deleted and the marker is off, the assertion stays.
  Verified live against Gemini — 7/7 verified on attempt 1, where the first live run
  needed the re-ask loop for this fixture, and 8/8 on the new header fixture.
- [x] 7. **MinIO storage backend** (2026-08-08). `MinioStorage` sits beside
  `LocalStorage` and nothing above `app/storage.py` can tell them apart. The part
  that matters is the error mapping: `jobs.is_retryable` treats
  `ObjectNotFoundError` as *permanent*, so only a 404 may map to it and every other
  fault — a refused connection, a timeout, a 500 — must stay a plain `StorageError`
  and be retried. Backwards, a thirty-second MinIO restart would permanently fail
  every resume uploaded during it, so that rule is pinned on every run against a stub
  client rather than only where a server is up. boto3 (so the same adapter points at
  real S3 later) in `asyncio.to_thread`, the move `process_resume` already makes for
  parsing. A missing bucket is refused at startup like `build_ocr_engine`'s
  language-pack probe; compose creates it in a one-shot service shaped like
  `migrate`, so `build_storage` never creates one and a typo in `MINIO_BUCKET` fails
  loudly. `tests/storage_contract.py` is written once and run twice — against
  `LocalStorage` on every `pytest -q`, against real MinIO on `TEST_MINIO_ENDPOINT`.
  Verified live in the containers with real Gemini: `pending` in 22 ms, `extracted`
  in 10.2 s, 10/10 verified with every span slicing back out, the blob in the bucket,
  nothing written to the uploads volume, and a re-upload deduped to the same row
  without billing a second extraction.
- [x] 8. Evidence viewer, text-layer only (`web/components/DocumentPane.tsx`).
  The true pdf.js overlay needs bbox geometry. #6 now extracts that geometry per
  page, so the remaining work is an endpoint serving the original file and a pdf.js
  canvas — it is a frontend slice now, not a parser one. Left for M5's recruiter UI.
  *(M3 slice 5 generalized this component from `ExtractedProfile` to `EvidenceRef[]`,
  so it now highlights judgment citations too. The pdf.js overlay is still M5's.)*

**Both M2 renders nobody had watched are now closed** (2026-08-12, with M3 slice 5):
a two-column resume reads CONTACT/SKILLS through before EXPERIENCE in `DocumentPane`
rather than interleaving, and an upload under `STORAGE_BACKEND=minio` renders the same
page with the object in the bucket and **absent** from the uploads volume.

## M2 follow-ups — the open questions M2 left behind (2026-08-08)

- [x] **OCR confidence gating.** The hole M2 #4 left: a badly degraded scan does not
  fail, it succeeds with nonsense — at 6px blur the page still clears
  `MIN_CHARS_PER_TEXT_PAGE` while "Somchai Jaidee" reads "Sore hector". A character
  count cannot tell text from noise; Tesseract's per-word confidence can.
  `OCR_MIN_CONFIDENCE` drops a page below the bar into the path a page that
  recognized nothing already takes, so the user gets "the scan may be too low
  quality" instead of a confident profile of the wrong words. The threshold is
  measured, not chosen: `tests/tools/ocr_degradation.py` is committed this time, and
  every degradation that still yielded the fixture's content scored 90.2+ while every
  one that yielded none scored 47.4 or less. The default 75 sits low in that gap
  because the fixtures are clean synthetic renders and a real photograph will score
  lower while still being readable. Costs a second Tesseract call per accepted page,
  because TSV tokenizes Thai per glyph and so cannot supply the text.
- [x] **A deliberately malformed PDF fixture**, open since 2026-08-07.
  `resume_broken_tounicode.pdf` reproduces the §11 incident with a real file: a
  well-formed ToUnicode map that says several glyphs mean U+0000. Written by hand,
  because reportlab only ever writes correct maps — and because *removing* the map,
  the obvious approach, produces `(cid:N)` placeholders instead, which is a different
  defect.
- [x] **The visibility timeout** for a worker that dies mid-job, the last §11
  follow-up. **Moved out of M5 and into M4 as slice 1** and shipped there
  (2026-08-12): it was the only open item that could strand a user's data with no way
  back through the API, which makes it a correctness item rather than an
  observability one. **Nothing from the §11 incident is outstanding now.**

## M3 — matching engine

Scope reviewed and agreed with the owner on 2026-08-08, replacing the draft
reconstructed from the README. Four calls were made before any code:

| Question | Decision |
|---|---|
| Where hybrid retrieval sits | **Last slice**, behind a seam, lexical as the no-server default and pgvector opt-in — the suite runs on in-memory SQLite and must keep doing so |
| Verdict vocabulary | **`met` / `not_evidenced`.** Absence cannot be quoted, so the system never asserts that a candidate lacks something |
| Where requirements come from | **Typed in through CRUD.** A requirement is an input, not a claim about a person |
| UI in M3 | **A thin one**, enough to watch a screening render in a browser. The full recruiter UI stays in M5 |

And three taken by default: a job is owned by a `Candidate` row (RBAC widens *who*
in M4 without changing the table); a screening is a first-class row with its own
background job, **sharing** the retry policy rather than copying it; and
`resumes.page_spans` is stored so a judgment quote maps to a page without
re-parsing — shipped in migration `0005` with `ParsedDocument.from_stored`, which
rebuilds a document from the row alone and parses nothing, deliberately unlike
`reparse_document`. Not backfilled: pre-`0005` rows report page 1, because filling
them in would mean re-parsing every stored file under the identical OCR
configuration.

**The idea that makes the guardrail generalize:** the model is never asked for a
verdict. It is asked only for quotes showing a requirement is met, and to omit the
requirement otherwise. The verdict is *derived* — at least one quote resolved is
`met`, nothing resolved is `not_evidenced`, and every quote that failed lands in
`dropped` and in the hallucination rate. The one thing a model could assert
unverifiably, it is never given the chance to say. `not_evidenced` is also the
honest label: the system cannot tell "the candidate lacks it" from "the resume does
not mention it".

- [x] 1. **Jobs and requirements as rows, with CRUD** (2026-08-08).
  `app/models/matching.py`: a `Job` owned by a candidate, and `JobRequirement`
  carrying `kind`, `label`, optional `detail`, `must_have` and `weight` — the two
  fields ranking later reads, with `must_have` a hard gate rather than a heavy
  weight. Requirement routes are nested under their job (`app/api/routes/jobs.py`)
  so ownership is settled in one place and a requirement is never reachable by
  guessing its id; every lookup answers **404, not 403**, matching `_owned_resume`.
  Capped at `MAX_REQUIREMENTS_PER_JOB=30` because the whole list travels in one
  judging prompt. Migration `0004` round-trips on real Postgres with no drift.
  Pinned by `tests/test_jobs.py` (25 cases; suite 270 → 295).
  Two things the verification caught that no test would have: the `ck` naming
  convention in `models/base.py` is the only one that interpolates
  `%(constraint_name)s`, so a check constraint spelled out in full in a migration
  gets wrapped twice and `alembic check` reports drift forever; and
  `RequirementKind` persists as enum **names** (`SKILL`), like `ResumeStatus`
  before it, so the migration declares the upper-case forms rather than repeating
  `0001`'s misleading value list.
- [x] 2. **Requirement-level judging** (2026-08-08). `app/pipeline/judge.py` and
  `app/schemas/judgment.py`, twins of `extract.py` / `extraction.py`. `EvidenceRef`,
  `DroppedClaim` and `EvidenceStats` are reused **unchanged**, so the hallucination
  metric covers judging for free and no part of the guardrail was reimplemented. One
  model call per screening carries the whole document and the whole requirement list.
  `resumes.page_spans` landed first as its own commit (migration `0005`), and
  `app/llm/fake.py` learned `RawJudgment` — not optional, since it raises for any
  other schema and the suite would otherwise need an API key.
  Three decisions inside it:
  **the model refers to a requirement by 1-based number, not UUID** — cheaper in
  tokens, and unlike a garbled UUID an out-of-range number is something the verifier
  can catch, so it becomes `RejectReason.UNKNOWN_REQUIREMENT` rather than vanishing,
  while duplicate numbers merge instead of overwriting;
  **the retry loop keeps the attempt with the most requirements *met***, where
  `extract_profile` keeps the fewest rejections — the retry prompt tells the model to
  leave a requirement out rather than reword a bad quote, so a compliant second
  attempt can answer about nothing, score zero rejections, and on extraction's rule
  win while discarding requirements the first attempt had proven;
  and **an empty requirement list never reaches the model**, because this path runs
  once per resume per job.
  `--requirement kind:label` on `app/cli.py` is a flag rather than a subcommand, so
  the bare command `CLAUDE.md` names stays byte-identical — verified by diffing three
  fixtures against the previous commit's CLI. Pinned by `tests/test_judge.py` (32
  cases; suite 307 → 339), and the three decisions above were each confirmed
  load-bearing by mutating the code and watching the suite fail.
- [x] 3. **Screening as a row, on the background worker** (2026-08-08). `screenings`
  carries the same four job-state columns `Resume` does, its result JSON, its stats
  lifted into real columns, and a `requirements_hash`. `decide_retry` came out of
  `app/jobs.py` as a pure function answering in **intents** — `PERMANENT` / `RETRY` /
  `EXHAUSTED` — rather than statuses, because `Resume` and `Screening` keep separate
  status enums (a screening is never `parsed` or `extracted`) and sharing one would
  leak each table's states into the other. `run_resume_job` behaves identically and
  `tests/test_retry.py` passed untouched, which was the point of the constraint.
  Three decisions inside it:
  **the fingerprint covers what the judge was shown** — kind, label, detail and their
  *order*, since the model refers to requirements by position — and deliberately
  excludes `must_have` and `weight`, which never reach the prompt, so nudging a weight
  cannot re-bill every screening; `prompt_version` sits beside the hash rather than
  inside it, so "the requirements changed" and "we changed the prompt" stay
  distinguishable.
  **A completed screening is not skipped by the job** the way an extracted resume is,
  because its requirements can change — waste is prevented one layer up, in
  `request_screening`, which queues only when the fingerprint moved. `POST` answers
  **202** when it queued and **200** when the stored result already answers.
  **A judging call is billed to the screening, not the resume** (`llm_call_logs.screening_id`),
  or "what did extracting this document cost" would be wrong.
  A resume with no `document_text` raises `NotScreenable`, which `is_retryable` treats
  as permanent. Routes: `POST/GET /jobs/{id}/screenings`, `GET /screenings/{id}`,
  `POST /screenings/{id}/retry` — 404 not 403 throughout. Migration `0006` round-trips
  on Postgres with no drift. Pinned by `tests/test_screening.py` (40 cases; suite
  339 → 379), and verified live through the containers against real Gemini.
- [x] 4. **Ranking across candidates** (2026-08-08). `app/pipeline/ranking.py` +
  `app/schemas/ranking.py`, judging's downstream twin: a pure function, **no model
  call, no new table, no migration**. Must-haves are a hard gate, within a tier it is
  the weighted share of requirements met, and the order ends on the screening id so a
  list never reshuffles between identical runs. Each entry carries its
  `RequirementJudgment`s — verdicts with citations — because the rationale is the
  evidence, not the number. `GET /jobs/{job_id}/ranking` on the existing
  `screenings.py`; `list_screenings` keeps its contract as the raw list.
  Two decisions inside it:
  **`must_have` and `weight` are read from the current `JobRequirement` rows, never
  from the stored `result`.** The judgment froze both at judging time, and the
  fingerprint excludes both on purpose — so editing a weight leaves the screening
  current while the stored JSON keeps the old number forever. Reading them back out of
  `result` is the obvious implementation and it silently makes weight edits do
  nothing. The join is **by position, not by id**, because the fingerprint excludes ids
  too; a length mismatch is excluded as `malformed` rather than joined against the
  wrong requirement.
  **A stale screening is excluded and reported, not re-run.** Ranking never spends a
  model call the caller did not ask for, and never mixes answers to two questions;
  `POST /jobs/{id}/screenings` stays the place a caller chooses to pay.
  Pinned by `tests/test_ranking.py` (32 cases; suite 379 → 411), and the three
  decisions were each confirmed load-bearing by mutation: reading weights from the
  stored result fails 5 cases, treating `must_have` as a heavy weight fails 3, and
  dropping the id tie-break fails 2.
- [x] 5. **A thin web UI** (2026-08-12). `web/app/jobs/page.tsx` authors a job with its
  requirements in one call; `web/app/jobs/[id]/page.tsx` edits them, screens resumes,
  shows the ranking and drills into one candidate's verdicts beside the document.
  **No API change and no migration** — `GET /jobs/{id}/ranking` already returned
  verdicts *with* citations, so a list view needs no second request per candidate.
  `DocumentPane` stopped taking an `ExtractedProfile` and takes `EvidenceRef[]`, which
  is the whole reason a judgment's citations highlight through the same component that
  M1's profile citations do.
  Three decisions inside it:
  **verdicts are rendered from the ranking entry, never from `GET /screenings/{id}`.**
  That route returns the stored `Judgment` verbatim, with `must_have` and `weight`
  frozen at judging time; ranking re-keys both against the job's current requirements.
  Reading them from the detail route is the obvious implementation and makes weight
  edits do nothing, silently — the same trap slice 4 documented on the server, in a new
  costume. The detail route is called for `document_text` and nothing else.
  **The cost of an edit is shown before it is made.** `must_have`/`weight` say "Free —
  reorders the ranking without re-judging anyone"; `kind`/`label`/`detail` say the
  screenings become stale. Edits stage behind a Save button so the warning arrives
  before the write, and nothing on the page ever loops `POST /jobs/{id}/screenings`.
  **`collectJudgmentEvidence` filters on the verdict rather than flattening.** The
  server sends no evidence for `not_evidenced`, so on the contract the two agree — but
  this side did not build that JSON, and the rule it must keep is that nothing is
  highlighted unless it produced a verdict. Written that way *because* the flattening
  version made its own test unable to fail.
  Screenings have no progress stream, so a queued one is followed by polling
  `GET /jobs/{id}/screenings` — one request for all of them, not one per row.
  Pinned by `web/lib/screening.test.ts` + new cases in `api.test.ts` (vitest 9 → 28,
  still with no React testing library and no DOM), and each of the three decisions was
  confirmed load-bearing by mutation. Verified in a browser against the containers and
  real Gemini, which also closed the two-column and MinIO renders left over from M2.
- [x] 6. **Retrieval, the pre-filter** (2026-08-12). `app/pipeline/retrieval.py` — a
  `Retriever` seam shaped like `Storage` and `OCREngine`, with `LexicalRetriever` as
  the no-server default and `GET /jobs/{job_id}/candidates` serving it. **No model
  call, no new table, no migration**, like ranking. `PgVectorRetriever` raises exactly
  as `LLM_PROVIDER=anthropic` does: embeddings are a paid call, so it lands only with a
  price table in the adapter and a live verification run in `docs/llm-providers.md`.
  Four decisions inside it:
  **Thai is tokenized by character n-gram, Latin by word — measured, not assumed.**
  `resume_th.pdf` contains the unbroken 31-character run
  `ดูแลระบบกระทบยอดการชำระเงินด้วย`, and the real terms `ชำระเงิน` and `วิศวกรรม` sit
  inside it where a whitespace tokenizer finds **neither**. The same measurement showed
  why a test could hide this: `ทักษะ` happens to be followed by a colon, so it *is* a
  standalone token and a naive tokenizer looks correct on it — the two-column fixture
  with no header, in a new costume. The Thai test cases use terms buried mid-run.
  **It is a hint, never a gate.** `retrieve` scores every document and returns all of
  them, ordered; it never drops the tail. A retriever that filtered would remove a
  person from consideration with no way to see it happened — the failure `excluded`
  exists to prevent one layer down. The cut-off is the caller's, made in the open.
  **`job.description` is not matched on.** It is stored for context and audit and is
  deliberately not what anyone is judged against; letting it steer retrieval would
  reintroduce free-text scoring on the one input nobody decomposed on purpose.
  **The order ends on the resume id**, so a list never reshuffles between identical
  runs — the lesson `test_ranking.py` paid for.
  Pinned by `tests/test_retrieval.py` (28 cases; suite 411 → 439), and each decision
  was confirmed load-bearing by mutation: 5, 9, 1 and 2 cases fail respectively.
  Verified live in the containers: a Thai requirement put `resume_th.pdf` first, the
  resume containing every word of the *description* still scored 0.0, and `psql` shows
  **zero** judging calls for the job.

**M3 is complete** (2026-08-12). A job posting and its requirements are rows with CRUD,
a resume is judged against them with every match cited, a screening is a row produced on
the worker under the shared retry policy, screenings are ordered into a ranking, there is
a UI a person can drive, and retrieval says where to spend the next model call. Three of
the six slices cost no model call and no migration at all.

## M4 — backend depth

Scope reviewed and agreed with the owner on 2026-08-12, replacing the draft
reconstructed from the README. Four calls were made before any code:

| Question | Decision |
|---|---|
| Whether an `Application` is a row | **Yes, a first-class one.** Today the system has no notion of who applied to what: a screening is `(job × resume)` that the job's owner pushes through. "applied → screened → shortlisted" only means something once applying does |
| RBAC shape | **A `role` column on `Candidate`** — candidate / recruiter / admin. HANDOFF §5 already promised M4 widens *who* may own a job without changing the table, and this keeps that promise |
| PDPA depth | **Delete and export first**, with consent captured as a flag at upload. A retention *scheduler* is a new piece of infrastructure and is deliberately not in this milestone |
| Where the visibility timeout goes | **Pulled forward to slice 1**, out of M5. It is the only open item that can strand a user's data with no way back through the API, and "fix remaining check-then-act races" is M4's own line — a row stuck at `processing` is that family |

**The idea that carries the guardrail into this milestone:** HANDOFF §9 asked that
anything M4 adds which *makes a claim* — a state transition, a shortlist decision —
get the same treatment as a verdict: derived from something checkable, or not
asserted. Applied here, **an application's state is never asserted, it is derived
from an append-only log of transitions.** `Application.state` is a projection written
in the same transaction as the event that caused it, and replaying the events has to
reproduce it. Two rules fall out, and they are the point rather than a side effect:

- **You may not shortlist someone who has not been screened.** A shortlist is a claim
  about a person, so it must rest on evidence that exists; the event records the
  screening id it rests on.
- **A rejection requires a reason.** Nothing about a person disappears silently — the
  same instinct as `dropped` and `excluded`.

And one call taken by default: **idempotency stays a natural key, not an
`Idempotency-Key` table.** `uq_applications_job_candidate` is the same move as
`uq_resumes_candidate_content` and `uq_screenings_job_resume`, and 201-vs-200 carries
the answer the way 202-vs-200 already does on screenings. A key table would be a
second mechanism for something the schema already guarantees. The draft's wording was
"idempotency keys on submission endpoints"; this is the narrower reading, chosen to
match the pattern already in the codebase.

- [x] 1. **The visibility timeout** (2026-08-12). `jobs.reclaim_stalled` plus an arq
  cron in `app/worker.py`, once a minute and at startup, `unique=True` so replicas do
  not each reclaim the same row. **No migration and no new table** — the four
  job-state columns `decide_retry` was extracted for already carry everything.
  `JOB_VISIBILITY_TIMEOUT_SECONDS` defaults to **900**, far beyond any real job,
  because reaping a worker that is merely slow duplicates its work while reaping a
  dead one costs a requeue.
  Three decisions inside it:
  **it reuses `decide_retry` rather than resetting the status** — a reclaim counts
  against `failed_attempts`, so a document that kills its worker every time
  dead-letters instead of looping reap → requeue → die, which is the failure mode a
  reaper introduces;
  **listing candidates and reclaiming one are separate functions**, because
  `_record_failure` commits and drops the locks the list took — so each row is
  re-read `with_for_update` and re-tested, or a `POST /retry`, a worker claiming it
  afresh, or the original finishing would each get the budget spent on a live run;
  and **a `processing` row with no `last_attempt_at` counts as stalled**, since the
  claim writes both in one commit.
  Plus the manual half: `POST /resumes/{id}/retry` and `POST /screenings/{id}/retry`
  accept a stalled row and `can_retry` says so — what actually closes "no way back
  through the API", and the only half that exists under `QUEUE_BACKEND=inline`.
  Pinned by `tests/test_retry.py` (13 new cases; suite 439 → 452), and every decision
  was confirmed load-bearing by mutation: a plain status reset fails 3 cases, dropping
  the staleness re-check 1, the status re-check 2, both 3, and treating a missing
  timestamp as fresh 1.
  **One test had to be rewritten because it could not fail** — running two sweeps back
  to back proves nothing, since the second one's candidate query already excludes a row
  the first moved to `pending`, so the guard under the lock never ran. The fix was to
  the *code's shape*: the guard is its own function now and the test drives it.
  Verified live in the containers against real Gemini by killing a worker mid-job: the
  row stranded with a null `failure_reason`, `can_retry` flipped at **exactly** 30 s
  (29 s → 409, 31 s → 200, on Postgres), the sweep reclaimed it, and a Gemini 503 that
  arrived unplanned proved the budget guard by dead-lettering at 3 attempts rather than
  looping. A screening was reclaimed the same way and completed 2/2. `JOB_VISIBILITY_TIMEOUT_SECONDS`
  is passed through `docker-compose.yml` and documented in `.env.example`.
- [x] 2. **RBAC: a role on the one actor** (2026-08-12). `Role` on
  `app/models/core.py` and `require_role` in `app/api/deps.py`, migration `0007`.
  Applied only where it is real in this slice: authoring or changing a posting, its
  requirements, and the two screening routes that spend money. **Reads stay open to
  every role** — slice 3 has candidates applying to postings, which means seeing one
  first — and ownership still gates which rows they see.
  Three decisions inside it:
  **a role gates a route and ownership gates a row, so 403 and 404 never merge.**
  A role check is about a route that is listed in `/docs` and which the caller has
  plainly found; an ownership check is about an id, and a 403 there confirms the id
  exists. The role check runs as a dependency *before* any row is read, so a candidate
  hitting a real id and an invented one get byte-identical responses.
  **`require_role` grants `ADMIN` implicitly**, because a role system where every
  route must remember the superuser grows a hole the first time someone forgets.
  **The role is read from the row, never carried in the token** — in the JWT a
  demotion would do nothing until the token expired.
  The migration **derives its backfill from `jobs.owner_id`** rather than guessing a
  default, declares the upper-case enum names (`0004`'s lesson), and uses
  `batch_alter_table` so it runs on the SQLite CI checks it (`0006`'s lesson). Its one
  wart is written down: a downgrade discards the only record of a role, so re-running
  it demotes a recruiter who has not posted anything — watched on Postgres.
  Registration takes the role, because there is no other way to become a recruiter;
  `admin` is deliberately not self-selectable. **That employers are unverified is
  recorded in `README.md` as a limitation**, not hidden behind a check that proves
  nothing.
  Pinned by `tests/test_rbac.py` (17 cases; suite 452 → 469), and both decisions with
  a silent failure mode were confirmed load-bearing by mutation: answering 403 on
  ownership fails 7 cases, dropping the implicit admin fails 1. Verified live in the
  containers and through a Postgres round-trip with `alembic check` clean.
- [ ] 3. **The application and its state machine** (migration `0008`). Also fixes the
  two things RBAC breaks, both named in HANDOFF §9: `_owned_resume` widens to a resume
  applied to a job you own, and `GET /jobs/{id}/candidates` stops joining filenames
  client-side on the assumption that every screened resume belongs to the caller.
- [ ] 4. **PDPA: consent, export, delete** (migration `0009`). `DELETE /me` removes
  **blobs first, then rows, and aborts without deleting anything if a blob cannot
  go** — so "deleted" is never a lie. The other order leaves an object in MinIO that
  no row points at, which is the actual PDPA failure; a row pointing at a missing
  blob is already a handled state.
- [ ] 5. **A thin UI** for the journey, cuttable. The same call M3 made: enough for a
  person to drive it in a browser, with the full recruiter UI still M5.

Deliberately **not** in M4: `next@16` (3 high advisories, all transitive through
Next — an isolated commit, not tangled into a slice), the refresh-token denylist and
httpOnly cookies (below), and M6's evaluation.

## M5 — recruiter UI, observability, ship (draft)

- Recruiter views: job list, candidate list per job, requirement-level match
  breakdown with citation highlighting, dropped-claims audit view.
- Observability: structured logs shipped somewhere queryable, request metrics,
  cost dashboard from `llm_call_logs`.
- [x] **Containerize API + web; compose runs the whole stack** (2026-08-08 — pulled
  forward from M5 because a course deliverable required Docker Compose to manage the
  containers). `api/Dockerfile` builds one image for both the API and the ARQ worker,
  since `app/worker.py` is a thin adapter over `app/jobs.py` and separate images
  would let their dependencies drift; `web/Dockerfile` uses Next's `standalone`
  output so the runtime image carries no `node_modules`. Migrations run as their own
  one-shot service rather than in an entrypoint, so replicas cannot race to apply
  them. Tesseract with `tha`+`eng` is installed in the API image, which removes the
  portable-install `OCR_COMMAND` quirk inside containers. Verified live against
  Postgres + Redis + ARQ + real Gemini: `resume_th.pdf` 10/10 verified and
  `resume_scanned.pdf` 7/7 with `pages_from_ocr=[1]`, every span slicing back out of
  the stored text.
- Still open: run the compose stack in production mode, and httpOnly cookie auth
  instead of localStorage.

## Auth — beyond M1

- [x] **`POST /auth/change-password`** (2026-08-08). Proves the current password,
  then issues a fresh pair. Tokens issued earlier keep working until they expire —
  revoking them needs a refresh-token denylist, which is also the reason there is no
  `/auth/logout`. The limitation is pinned by a characterization test in
  `tests/test_api.py::TestChangePassword` rather than left to be discovered.
- [ ] Refresh-token denylist, which would unlock a real `/auth/logout` and let a
  password change revoke outstanding sessions. Considered for M4's scope review on
  2026-08-12 and deliberately left out — it is a storage decision (where a denylist
  lives, and how it is swept) rather than an authorization one, and none of M4's four
  commitments need it. Raise it again if PDPA's delete path makes it cheap.

## M6 — optional evaluation (draft, one-week timebox)

Ranking quality against a BM25/embedding baseline needs a labelled gold set.
Deliberately out of the critical path: the free metrics (hallucination rate, parse
success, cost per document) already ship in M1–M2. If the timebox expires, stop.
