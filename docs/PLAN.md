# Milestone plan

The working plan for HireLens, kept in the repository so any session — human or
agent — can see where the project is and what comes next. Update the status
column and checklists as work lands; refresh `docs/HANDOFF.md` when a milestone
completes.

M1–M2 reflect decisions already made and verified, and so do **M3**, **M4** and now
**M5** — their scopes were each reviewed with the owner (M3 on 2026-08-08, M4 on
2026-08-12, M5 on 2026-08-13), so the decisions and slices below are commitments
rather than a reconstruction. **M6 is still a draft** reconstructed from the README
milestone table and HANDOFF scope notes — review it the same way before treating the
details as commitments. Three reviews, three times it paid: M5's turned a one-line
"recruiter views" bullet into three items, two of which were already shipped, and
caught a load-bearing claim about the codebase that was false.

| Milestone | Scope | Status |
|---|---|---|
| M1 | Parse (PDF, offsets, Thai), extract, verify evidence, retry, auth, upload API, web UI | ✅ done (2026-07-30) |
| M2 | Async worker + queue, OCR, DOCX, two-column fix, MinIO, PDF viewer overlay | ✅ done (2026-08-08) |
| M3 | Job requirements, hybrid retrieval, requirement-level judging, ranking | ✅ done (2026-08-12) |
| M4 | Visibility timeout, RBAC, the application state machine, PDPA | ✅ done (2026-08-12) |
| M5 | Dropped-claims view, cost dashboard, word geometry + pdf.js overlay, production compose | scoped 2026-08-13 |
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
  The true pdf.js overlay needs bbox geometry. ~~#6 now extracts that geometry per
  page, so the remaining work is an endpoint serving the original file and a pdf.js
  canvas — it is a frontend slice now, not a parser one.~~
  **Corrected 2026-08-13, during M5's scope review: that was wrong.** `layout.py`
  computes bounding boxes to *crop* columns and discards them inside the same
  function; nothing persists them. `PageSpan` holds
  `page_number`/`char_start`/`char_end` and `EvidenceRef` holds
  `char_start`/`char_end`/`page`, so **no stored row can say where on a page a
  character range sits** — and a two-column page's `document_text` is in reading
  order rather than the PDF's internal order, so a client cannot re-derive it either.
  The overlay is therefore a **parser slice plus a frontend slice**, with a migration
  between them; it is M5 slices 3 and 4.
  *(M3 slice 5 generalized this component from `ExtractedProfile` to `EvidenceRef[]`,
  so it now highlights judgment citations too.)*

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
- [x] 3. **The application and its state machine** (2026-08-12). `Application` and an
  append-only `ApplicationEvent` (migration `0008`), the rules as a **pure** module
  (`app/applications.py`, no session — the shape `decide_retry` and `rank_screenings`
  established), `app/services/application_service.py` as the only writer of `state`,
  and five routes.
  The idea, with a body: **the state is a projection of the log**, written only in the
  same transaction as the event that caused it, and replaying the log has to reproduce
  it. Two rules fall out rather than being bolted on — **a shortlist is reachable only
  from `screened` and records the screening id it rests on**, and **a rejection needs a
  reason**. `screening` and `screened` are set by the worker from the `Screening` row,
  which is the "derived from something checkable" clause; every other move is somebody's
  decision, and an illegal one is **refused with its reason (409)**, never ignored.
  Also closes the two things RBAC broke, both named in HANDOFF §9: `_owned_resume`
  widens to a resume applied to a job you own — for **reads only**, since replaying an
  extraction belongs to whoever uploaded it — and the ranking serves `resume_filename`
  instead of leaving the client to join it from `GET /resumes`, which returns the
  caller's own and no longer covers the list.
  Two things the live run found that the suite did not:
  **every recruiter decision was being logged as the system's.** `Actor` derived the
  account id from the mover, and the job owner's id is not on the application, so
  `actor_id` came back null. The test asserted `actor_role`, which was correct. `Actor`
  carries the id now, and the assertion names *who*.
  And **the log came back shuffled**: SQLite's `CURRENT_TIMESTAMP` has one-second
  granularity, so every event in a fast journey shares a timestamp and the tiebreak was
  a random UUID. Ordering is a stored `position` with a unique constraint behind it.
  Pinned by `tests/test_applications.py` (39 cases; suite 469 → 508), with six decisions
  confirmed load-bearing by mutation. Verified live in the containers against Gemini:
  404-then-200 on the applicant's resume, 409 on both guarded moves, the four-row audit
  log read out of `psql` with its actors and evidence, a Thai requirement at 36 chars /
  90 bytes, and a ranking naming a resume the recruiter's own `GET /resumes` returns
  zero of. Migration round-trips on Postgres and SQLite with `alembic check` clean.
- [x] 4. **PDPA: consent, export, delete** (2026-08-12). `app/services/privacy_service.py`
  holds both rights in one module because they are the same question asked twice —
  export says what is held about you, delete removes exactly that, and if the two
  disagree one of them is lying. Migration `0009` adds `consented_at` and
  `consent_version` to `resumes`, **nullable and deliberately not backfilled**:
  nobody was asked, and writing "now" onto old rows would fabricate an agreement.
  Four decisions inside it:
  **erasure deletes stored files before rows and abandons everything if one refuses**
  (503, nothing changed). The other order leaves an object no row points at —
  undiscoverable and so unerasable, which is the real PDPA failure; a row whose file
  is missing is already a handled, reported state.
  **Export is a subject-access request, not a dump of everything you can see.** A
  recruiter may read an applicant's resume and it is still not theirs to export. What
  comes back *is* the substance — `document_text` and the verified profile — because
  withholding it would make the right to a copy decorative.
  **Consent has no default and carries its version.** A field defaulting to true is
  not consent, so a missing one is a 422 from the schema, before anything is stored.
  `GET /resumes/consent` serves the wording so a client shows it rather than inventing
  its own, and the web client sends what the box says rather than a hard-coded `true`.
  **SQLite is told to enforce foreign keys.** Found by writing the cascade test and
  watching it fail for the wrong reason: SQLite ignores every `ON DELETE` clause
  unless asked, so `CASCADE` and `SET NULL` were inert there and live on Postgres —
  and the whole suite runs on SQLite. Same class as SQLite storing the NUL Postgres
  refused.
  Pinned by `tests/test_pdpa.py` (21 cases; suite 508 → 529) plus 2 vitest cases, and
  all four confirmed load-bearing by mutation: 4, 1, 1 and 2 cases fail respectively.
  Verified live **on `STORAGE_BACKEND=minio`** on purpose — a filesystem cannot show
  "the object outlived the row" the way a bucket can: `mc ls` reports **0 objects**
  under the account's prefix afterwards, `psql` 0 rows, and the token 401.
- [x] 5. **A thin UI for the journey** (2026-08-12). `web/app/applications/` is the
  candidate's half — apply, follow, withdraw — and `/jobs/[id]` gains an applicants
  panel grouped by state. **No API change and no migration**: `ApplicationOut` already
  carried `job_title` and `resume_filename`, so a list needs no second request per row,
  exactly as `GET /jobs/{id}/ranking` did for M3's slice 5. `lib/applications.ts` keeps
  the logic pure so `npm test` still needs no DOM.
  Two decisions inside it:
  **the client offers moves; it does not decide them.** The rules live on the server
  and a second copy here would be the one that drifts unnoticed, so `availableMoves`
  mirrors the table without re-deriving its reasoning — and when the two disagree the
  409 wins and its sentence is what gets shown.
  **A move that is not available yet is disabled with the reason, not hidden.** A
  missing button is indistinguishable from a bug; one that says "screen this candidate
  first, so the decision rests on cited evidence" is what teaches the rule.
  Pinned by `lib/applications.test.ts` (vitest 30 → 43), and four decisions confirmed
  load-bearing by mutation — hiding the blocked shortlist, dropping the reason
  requirement, not treating an admin as the owner, and attributing the system's moves
  to a person each fail a case.
  **Verified as far as it can be without a browser, and not further.** Every call each
  screen makes was exercised against the containers and live Gemini; the timeline text
  matches `describeEvent` exactly; the container serves the new bundle. **Nobody has
  watched it render** — the Chrome extension was not connected — and that gap is
  recorded in `HANDOFF.md` §1 rather than glossed over.

  **Watched on 2026-08-13, and the gap was not cosmetic.** Seven defects, four of them
  blocking, in a slice where every gate was green and every call was verified:
  a candidate could not see any posting (`GET /jobs` filtered by owner, so `200 []`);
  `Create job` would not submit (the weight input's `min=0.1 step=0.5` rejected its own
  default of `1`); a recruiter could not screen an applicant (the picker was built from
  `GET /resumes`, which returns only their own), so the disabled Shortlist could never
  unlock; and **every transition answered 422**, because `moveApplication` and
  `applyToJob` skipped the `json()` helper and sent no `Content-Type`.
  All four are fixed, each as its own commit with a test that fails without it, and the
  whole journey was then re-walked in a browser with no `curl` anywhere.
  **The remaining three are closed too**, same day, one commit each: registration now
  offers the two self-service roles (and says plainly that nothing verifies an
  employer), the blocked-Shortlist sentence has one reason per state instead of one for
  everything-but-`screened`, and the applicants panel re-reads itself when a screening
  moves it. Only the third has no unit test, and deliberately: it is a component
  effect, `web/` has vitest with no DOM by design, and the two candidate tests were
  rejected as a re-implementation of the server's `_ALLOWED` table and as a tautology.
  The check for it is the browser, where the panel was watched moving
  `APPLIED → BEING SCREENED → SCREENED` on its own and the Shortlist enabling without a
  reload. Gates: vitest **43 → 62**, `pytest` **529 → 534**.
  **The lesson is the one the slice's own note asked for:** verifying every call a
  screen makes is not the same as using the screen, and the four blocking defects were
  all wiring — invisible to a suite that tests pure logic, which is what
  `lib/applications.ts`'s 13 cases do.

Deliberately **not** in M4: `next@16` (3 high advisories, all transitive through
Next — an isolated commit, not tangled into a slice; **shipped 2026-08-13**, see the
M5 section), the refresh-token denylist and httpOnly cookies (below), and M6's
evaluation.

**M4 is complete** (2026-08-12). A dead worker's row is reclaimed through the retry
policy it already had; an account has a role, and a role gates a route while ownership
still gates a row; a candidate applies, and every move that application makes is an
entry in an append-only log that the state is merely a projection of; and a person can
take a copy of what is held about them or have it erased, files before rows. Two of the
five slices needed no migration and none needed a new idea about evidence — the
guardrail generalised to state transitions the same way it generalised to verdicts in
M3.

## M5 — recruiter UI, observability, ship

Scope reviewed and agreed with the owner on 2026-08-13, replacing the draft
reconstructed from the README. The review paid for itself immediately: the draft's
one-line "recruiter views" bullet was **two thirds already shipped**, and its
remaining third turned out to rest on a claim about the codebase that is false.

| Question | Decision |
|---|---|
| What is actually left of the recruiter UI | **Three things.** Job list, candidate list per job and the requirement-level breakdown with citation highlighting all shipped in M3 slice 5 and M4 slice 5. What remains is the **dropped-claims audit view**, a **cost and quality dashboard**, and the **pdf.js overlay** parked since M2 #8 |
| Whether the overlay justifies a route serving raw PII bytes | **Yes, on the ownership rule that already exists.** `_owned_resume` — the uploader, and a recruiter the candidate applied to — 404 rather than 403, `no-store`, and no filename in any log. A page that came from OCR has no geometry to overlay onto, so it falls back to the text pane **and says why**, rather than silently rendering nothing |
| Where the overlay's geometry comes from | **Stored at parse time, in its own slice with its own migration.** See below — this is the answer that changed the shape of the milestone |
| Observability shape | **An in-app dashboard over `llm_call_logs`.** Bounded, no new table, no new infrastructure, and it keeps "every dependency has a no-server default" intact. Shipping logs to something queryable would need a seam like `Storage`/`OCREngine`/`Retriever`, and nothing in M5 needs it yet |
| httpOnly cookies instead of localStorage | **Deferred again**, with the refresh-token denylist it drags in. It is a storage decision, and none of M5's commitments need it |
| What "deploy" means | **A production compose profile on this machine, plus a runbook.** Secrets out of `.env`, restart policies, Postgres and Redis not published to the host. A real cloud host is a bigger question than this milestone |
| jsdom in `web/` | **Not yet.** The `next@16` browser check caught everything jsdom would have and several things it could not — whether the stylesheet actually loaded, whether SSE still streams. The no-DOM property stays, and driving the browser *inside* the slice stays the check |

**The organizing idea, confirmed rather than assumed:** *every number on an
observability screen is a query over rows the system already wrote, and can name the
rows it came from.* Cite your source, applied to metrics. That is the same move as
M3's "a verdict is derived from a located quote" and M4's "a state is a projection of
an event log", a third time — and the schema is already shaped for it, which is the
sign it is the right idea rather than a slogan. `llm_call_logs` carries `provider`,
`model`, `prompt_version`, `attempt`, the three token counts, `latency_ms` and a
**nullable** `cost_usd` (null when the price is unknown, never a misleading zero);
`extracted_profiles` lifts `claims_verified`, `claims_dropped` and
`hallucination_rate` into real columns *specifically* so the metrics query is a
`GROUP BY` and not a JSON walk. `models/core.py` has said so in a docstring since M1.

**And the correction the review turned up.** M2 #8 and HANDOFF §9 both said the
pdf.js overlay was nearly free — that #6 "now extracts the bbox geometry it needs, so
the remaining work is an endpoint serving the original file and a pdf.js canvas".
**That is wrong.** `layout.py` computes bounding boxes to *crop* columns and discards
them inside the same function; `PageSpan` stores `page_number`/`char_start`/`char_end`
and `EvidenceRef` stores `char_start`/`char_end`/`page`. **No geometry is persisted
anywhere**, so nothing can say where on a page a character range sits. Worse, for a
two-column page `document_text` is in *reading* order, which is not the PDF's internal
order, so the mapping cannot be re-derived in a client either. Doing the matching in
pdf.js was considered and refused: the client would have to reproduce the server's NFC
normalization, NUL strip and column reordering, and when it drifted it would highlight
the wrong region — a visual claim nobody can verify, which is the one thing this
project refuses. So the geometry is measured where the offsets are measured, and the
overlay waits for it.

- [x] 1. **The dropped-claims audit view** (written 2026-08-14, **closed 2026-08-15 by
  watching it**). The guardrail's own evidence, which the
  system produces on every document and has never shown anyone. What the model said,
  why the quote could not be located, and the hallucination rate beside it.
  **No API change and no migration** — checked rather than assumed, the same way this
  section's correction was found: `ProfileOut.profile` is the stored `ExtractedProfile`
  serialized whole and already carries `dropped`, and `GET /screenings/{id}` returns
  the stored `Judgment` verbatim, `dropped` included — a route `/jobs/[id]` already
  calls for `document_text`. `RankedEntry` deliberately does not carry it.
  The rule to hold: this view **reports**, it never re-asks. Nothing on it may spend a
  model call.

  **Written 2026-08-14, in two commits, and deliberately still unticked.** The audit
  that preceded it corrected the description above: the *extraction* half shipped in
  M1 — `ProfileView.tsx` has shown the stat bar and the excluded-claims panel all
  along — so "has never shown anyone" was false, and the unbuilt half was **judging's**.
  A recruiter could read a candidate ranked #1 with no sign that the judgment behind it
  had thrown a fabricated quote away.
  `web/lib/evidence.ts` now holds the reason vocabulary, the panel wording and the
  stats formatting, with `components/DroppedClaims.tsx` and
  `components/EvidenceStatsBar.tsx` shared by both screens — the same move the server
  makes by importing `DroppedClaim` and `EvidenceStats` into `schemas/judgment.py`
  rather than declaring its own. Moving them out of the component is what made them
  testable: `unknown_requirement` is judging's reason and only judging's, and it sat
  correct and unreachable inside the profile view for two milestones.
  **No API change and no migration, as scoped** — `/jobs/[id]` already fetched the whole
  `ScreeningDetail` on every candidate click and used one field of it. Verdicts still
  come from the `RankedEntry`; that rule is about `must_have`/`weight` going stale, and
  nothing re-keys a dropped claim.
  Two server cases added (`pytest` 534 → 536) because the route was serving `dropped`
  by accident rather than by test — it returns the stored `Judgment` as an untyped dict,
  so nothing could strip it and nothing would have failed if something had. Plus 7
  vitest cases (62 → 69), three of them on failures that are silent: a reason with no
  label, an `isClean` derived from the rounded rate, and a model-call count read from
  the identically-spelled *job* counter.
  ~~**What is missing is the only thing that closes it: nobody has watched it.**~~
  **Watched 2026-08-15, and it works** — both blockers (a full `C:`, a disconnected
  Chrome extension) were gone, and the walkthrough spent **zero** Gemini quota on
  `FAKE_MODE=hallucinating`, which is the only way to make the panel speak: there is not
  one dropped claim in the dev database, because the real provider behaves.
  One recruiter account did it: `screenable` merges own uploads with applicants', so no
  application journey is needed to reach a screening. Extraction first — **10/11
  verified, 9.1% unverifiable, 2 model calls**, and the M1 panel still renders
  (`skills[5] Team leadership — no matching text in the document`), which is the
  regression check the shared-component refactor owed. Then the new half: clicking the
  ranked candidate showed **1/2 claims verified, 50.0% unverifiable, 2 model calls**,
  `Python` **Met** citing the Thai line `ดูแลระบบกระทบยอดการชำระเงินด้วย Python และ
  PostgreSQL` (p1 · chars 161–214 · exact), `Kubernetes` reading *"No citable evidence"*,
  and beneath them `Excluded — could not be traced to the document (1)` naming
  `requirements[1] Kubernetes` with the fabricated quote struck through.
  **The fabricated quote did not manufacture a verdict** — the requirement it was
  attached to still reads unevidenced, which is the sharper half of the test.
  Two things the browser proved that no test did. **The model-call count is read from
  `stats.attempts`, not the identically-spelled job counter**: `psql` shows the
  screening's own `attempts = 1` while the stats say `2`, and the screen said "2 model
  calls" — had it read the row it would have said one. And the console was clean **on an
  instrument proven to speak first** (a `console.log`/`console.error` probe pair,
  confirmed visible before the absence was believed). The throwaway account was erased
  afterwards: `stored_files_removed: 1`, the token then **401**, and `psql` reports 0
  accounts, 0 jobs, 0 screenings.
- [ ] 2. **The usage and quality dashboard.** A read route aggregating `llm_call_logs`
  and `extracted_profiles`, and a screen for it. **No migration.**

  **Respecified 2026-08-15, with the owner: this was a *cost* dashboard and there is no
  cost.** `app/llm/gemini.py:37-46` maps every model to `FREE_TIER`, so all 22 logged
  calls stored `cost_usd = 0.0` — and **not one is NULL**, which is the single behaviour
  the old spec said it must get right. Building it as written meant shipping a screen of
  zeroes that reads as a bug. Measured in `psql` rather than inferred, and worth keeping
  as the baseline the screen can be checked against: `extract-v1` 17 gemini calls at
  8,410 in / 27,439 out and avg 9,698 ms; `judge-v1` 1 call at 609 / 560 and 3,272 ms;
  4 `fake` calls at 585 / 0. So it charts what is real — **tokens, latency, calls per
  prompt family, re-ask attempts, hallucination rate, claims verified and dropped, parse
  success**. The `cost_usd IS NULL` rule stays written down for the day a paid provider
  exists (a stale price silently corrupting a cost figure is a named hazard in
  `CLAUDE.md`), and the slice gets renamed rather than the hazard forgotten.

  The organizing idea is unchanged: every figure is a query over rows the system already
  wrote and can name the rows it came from, and **nothing on it may spend a model call**.
  The extraction/judging split (`resume_id` xor `screening_id`) is what makes "what did
  this document cost" and "what did this screening cost" separately answerable, so the
  dashboard must not collapse it.

  Three constraints, each verified against the code on 2026-08-15 and confirmed by an
  independent challenge rather than left as a lead:
  **`llm_call_logs` has no owner column at all.** So "the caller's own rows" is two
  *arms* and three joins — `resume_id → resumes.candidate_id` for extraction,
  `screening_id → screenings → jobs.owner_id` for judging.
  **The `resume_id` xor `screening_id` invariant is a docstring, not a constraint.**
  Both columns are nullable with no `CHECK`, so a row with both null is legal today and
  would vanish from every owner-scoped total. Decide whether this slice adds the
  constraint or reports the orphans — but do not let them disappear silently, which is
  the same instinct as `dropped` and `excluded`.
  **`require_role` cannot widen a row scope.** It is a 403 route gate that runs no query
  and returns the caller unchanged, so the old line "`ADMIN` sees everything, via
  `require_role`" would 403 exactly the accounts that own the extraction rows.
  `api/app/api/routes/resumes.py:294` is the pattern for widening by role — but note
  `api/app/api/routes/jobs.py:222-223`, an existing role-branched set-level `WHERE` that
  **narrows** ADMIN to its own rows. Admin's set-level scope is genuinely unsettled in
  this codebase, so it is an owner decision and not just a change of mechanism.
- [ ] 3. **Word geometry, measured where the offsets are measured.** The slice the
  correction above created. Per-word boxes keyed to char ranges.

  **Corrected 2026-08-15 — this bullet used to say "written in `_assemble`, in the same
  pass that already measures page spans", and that is impossible.** `_assemble` is
  declared `_assemble(raw_pages: list[str], …)` (`parse.py:395-401`): it receives
  *strings*, never the pdfplumber `Page` objects, so geometry cannot be measured there
  under any implementation. Three things were measured rather than argued:
  the NUL strip runs on the whole page string *after* words exist (`parse.py:414`), so
  on `resume_broken_tounicode.pdf` **8 of 11 words carry a literal `\x00`** and word
  starts drift by up to **11 characters** between raw and assembled text;
  **`find()` is unsound even where there are no NULs** — 105 of 120 words in
  `resume_multipage.pdf` occur more than once, so first-occurrence matching would
  highlight the wrong word, silently;
  and the two-column path **reorders**, giving 11 offset inversions on
  `resume_two_column.pdf`, so visual word order is not char order.
  The mechanism that works is not searching at all: pdfplumber's textmap aligns
  characters to boxes **by construction** (verified — 85 tuples for an 85-char string,
  `to_string() == extract_text()`). Note the dependency risk: `Page._get_textmap` is
  underscore-private, while `chars_to_textmap` is public in `pdfplumber.utils.text`.
  So the real change set is: `_text_of` (`parse.py:282-294`) stops returning a bare
  `str`; `layout.extract_in_reading_order` (`layout.py:132-135`) returns geometry per
  crop region with a running offset; the NFC+NUL transform becomes an offset
  **remapping** rather than a `.replace()`; `_assemble` becomes where geometry is
  *rebased* into the document coordinate space rather than where it is measured; an
  OCR'd page discards its geometry (already the documented overlay fallback); and
  `parse_docx` (`parse.py:325`) needs the field optional from day one. Plus migration
  `0010`.
  **Not backfilled**, exactly like `page_spans` in `0005`: filling it in would mean
  re-parsing every stored file under the identical OCR configuration. Pre-migration
  resumes fall back to the text pane.
  This touches `parse.py`, the most load-bearing module in the project, so it is its
  own slice and its own commit. The property to pin: **every existing fixture's
  `document_text` and page spans are byte-identical before and after** — the M2 #6
  discipline, which is what keeps every citation already shown to a user pointing where
  it did.
- [ ] 4. **The pdf.js overlay**, on slice 3's geometry. `GET /resumes/{id}/file` behind
  `_owned_resume` (404 not 403, `no-store`, no filename logged) plus a pdf.js canvas.
  A page from OCR, or a resume written before slice 3's migration, falls back to
  `DocumentPane` **with the reason shown** — a silent fallback is indistinguishable
  from a bug, which is M4 slice 5's disabled-button lesson in a new place.
- [ ] 5. **Production compose and a runbook.** Secrets out of `.env`, restart policies,
  and Postgres/Redis not published to the host. Plus the runbook: how to bring it up,
  how to run migrations, what to check, how to erase an account on request.

  **The security half shipped early, on 2026-08-15, as its own commit** — it was the
  state of the dev machine rather than a question about a future deploy. Redis was
  published on every interface with no password (a raw socket answered `+PONG`;
  `CONFIG GET requirepass` came back empty), as were Postgres and MinIO. All three are
  `127.0.0.1:`-bound now, and both opt-in suites were re-run against the new binds to
  prove the bind was right rather than merely different.

  **Corrected 2026-08-15: this cannot be a compose `profiles:`,** which the scope review
  named. Measured on this machine (Compose **v5.3.1**): `profiles:` leaves
  `published: "5432"` untouched when active, and when *inactive* the project fails to
  load at all — `service "api" depends on undefined service "postgres": invalid compose
  project` — because every infra service is a `depends_on` target. A plain override
  **appends** rather than replaces (both ports published), and `ports: []` is a silent
  no-op. The `docker-compose.override.yml` inversion the 2026-08-14 notes prescribe is
  the pre-v2.24 answer and is no longer needed: `ports: !reset []` removes the key and
  `ports: !override [...]` replaces it, both verified working here. So keep
  `docker-compose.yml` as the dev file — that is what keeps the fresh-clone promise and
  `CLAUDE.md`'s opt-in test commands flag-free — and add a committed
  `docker-compose.prod.yml` run as `-f docker-compose.yml -f docker-compose.prod.yml`,
  with `COMPOSE_FILE` set on the prod host so a bare `up` there is prod.
  Two traps no document named: the `*api_env` YAML anchor **cannot cross files**
  (`unknown anchor 'api_env' referenced`), so prod env wants an `env_file:` shared by
  `api` and `worker`; and `NEXT_PUBLIC_API_BASE` is a **build arg**, so a prod URL means
  rebuilding the web image, not restarting it — as does the matching `CORS_ORIGINS`.

Each slice is driven in a browser *inside* the slice, not after it. That rule cost
seven defects to learn and the `next@16` check confirmed it is cheap to keep.

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
- [x] **`next@16`** (2026-08-13 — an isolated commit, deliberately not folded into a
  slice). Closes 3 high advisories: four postcss CVEs (XSS via an unescaped
  `</style>`; path traversal reading arbitrary `.map` files through an
  attacker-controlled `sourceMappingURL`) and four libvips CVEs through sharp, all
  transitive through `next@15.5.23` and none reachable except by the framework major.
  `npm audit` is 0.
  Four decisions inside it:
  **ESLint stays on 9.** The codemod bumped it to 10, and `eslint-config-next@16.3.0`
  depends on `eslint-plugin-react@^7.37.0`, whose newest release still caps at
  `eslint ^9.7` and dies on 10. The peer warning at install time was the whole answer.
  **`eslint.config.mjs` drops `FlatCompat`** for the flat arrays v16 exports directly
  — not a tidy-up: under ESLint 10 the old `compat.extends(...)` throws rather than
  degrading, which reads as a bug in this repo instead of a removed API.
  **`react-hooks/set-state-in-effect` is suppressed per site, not switched off.**
  Three of the four are false positives (setState after an `await`, which the rule's
  analysis does not follow); the fourth, in `useAuth`, is a real localStorage
  hydration and owes a `useSyncExternalStore` rewrite as its own commit.
  **`web/Dockerfile` is unchanged, and that was checked rather than assumed.**
  Turbopack is the default builder in 16 and has a known regression dropping packages
  from `.next/standalone/node_modules` (vercel/next.js#88844) — the exact directory
  the image copies while shipping none of its own. Verified by assembling the layout
  by hand and booting it, because a green `next build` cannot see this.
  Verified in a browser inside the change, against the rebuilt container and live
  Gemini for 2 model calls: upload → `10/10` verified with citation highlighting, the
  SSE progress stream serving 200, the applicants panel self-refreshing
  `APPLIED → BEING SCREENED → SCREENED` with nothing reloaded, 2/2 met including the
  Thai requirement at 36 chars / 90 bytes, the four-row audit log with its attribution
  intact, and zero console output on an instrument proven live first. Both throwaway
  accounts erased afterwards.
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
