# Working notes

Short, dated notes from working sessions: what happened, what comes next, and
advice for the owner. Newest entry first. The detailed records stay in
`HANDOFF.md` and `PLAN.md` — this file is the quick version, with pointers.

---

## 2026-08-08 (later) — M2 #4: a scan is no longer a dead end

### What was done

`OCR_ENGINE=tesseract` turns a scanned resume from a permanent `failed` into a
normal, fully cited profile. Tesseract 5.5.3 was installed this session with
`eng`, `tha` and `osd`.

- **`app/pipeline/ocr.py`** is the seam: an `OCREngine` ABC, `TesseractEngine`
  driven over stdin/stdout, and `build_ocr_engine`. Subprocess rather than a
  wrapper library — no new Python dependency, and the page image never touches
  disk, which matters because it is a picture of somebody's resume.
- **`parse.py` substitutes recognized text before `_assemble` measures spans.**
  That single decision is why nothing downstream changed: evidence offsets, page
  mapping and `DocumentPane` highlighting all kept working untouched. Same move as
  the NUL strip from the §11 incident.
- **Off by default** (`OCR_ENGINE=none`), so CI and a fresh clone are exactly as
  they were. The suite drives the whole path through a stub engine;
  `tests/test_ocr_tesseract.py` is opt-in on `OCR_TESSERACT_CMD`, in the shape of
  `tests/test_postgres.py`.
- **`pages_from_ocr`** is recorded on the resume (migration `0003`), returned by the
  API and surfaced in `ProfileView`, because a citation into an OCR'd page is
  faithful to what was *read*, not to what was printed.
- Suite grew 173 → 188 (`tests/test_ocr.py`), plus 6 opt-in. All gates green,
  including `tests/test_postgres.py` and the migration round-trip on real Postgres.

### Verified live, not only by tests

Against Postgres + ARQ + real Gemini, on a fresh port:

- **`resume_scanned.pdf`**: `pending` → `processing` → `extracted` in 5.7 s with
  `pages_from_ocr=[1]`. 7/7 verified, 0 dropped, every match tier-1 exact, all 7
  spans slicing back out of the stored text. **Three skills were cited straight out
  of the Thai OCR line** `ทักษะ: Python, FastAPI, PostgreSQL`.
- **`resume_mixed_scan.pdf`**: `pages_from_ocr=[2]` — page 1 kept its text layer,
  page 2 came from the image, 5/5 verified.
- Before/after on the CLI is the clearest single artifact: `parse failed: …requires
  OCR` becomes a profile with four exact citations.

### The decisions inside it

- **`OCREngine | None`, and `None` means off.** A null-object engine returns `""`
  both when OCR is disabled and when it read a page and found nothing. The second is
  a real answer about the document and must stay distinguishable.
- **The language pack is checked at startup, not per document.** A Tesseract without
  `tha` would keep working for English and return noise for Thai — the failure this
  project can least afford, and invisible until someone reads the output. Same class
  of silent corruption as a stale price table.
- **Recognized text below the text-layer threshold is thrown away** rather than
  stored. A handful of noise characters is not text anybody wrote, and this project
  only quotes text somebody did.

### What bit, and what to do about it

- **A stale ARQ worker from the previous session stole the first job** and marked the
  scan `failed` with the *old* error message — pre-OCR code, still polling the same
  Redis queue. `NOTES.md` already warned "stop the other workers first"; it cost ten
  minutes anyway because the symptom looks exactly like a bug in the new code. The
  giveaway was the wording of `failure_reason` in the database. **Check
  `Get-CimInstance Win32_Process | Where CommandLine -like '*arq*'` before believing
  any live run.** All arq workers are stopped now — start one when you next need it.
- **The zombie API on :8000 and a dev server on :3000 are still there**, unchanged
  from the last entry. Still worth a reboot.
- **`ALLOWED_ORIGINS` blocked the browser check**, so it was fixed in the same
  session rather than deferred a third time: it is now the `CORS_ORIGINS` setting
  (comma-separated, `NoDecode` so it does not demand JSON), pinned by
  `TestCorsOrigins` in `tests/test_config.py`. The empty `app/workers/` package went
  with it. Both had been sitting on this list for two sessions; the trigger for
  finally doing them was one of them blocking verification of real work.
  **With that unblocked the banner was checked by eye** on :3002 — it reads "Page 1
  had no text layer and was read by OCR…", `7/7 claims verified`, and the document
  pane carries six highlights over the recognized text, two of them inside the Thai
  line. The lesson worth keeping: the cleanup was not cosmetic, it was the thing
  standing between the work and its verification.

### Also landed this session

- **M2 #5 — DOCX.** `parse_docx` reads paragraphs *and tables* in document order.
  The table part is the whole point: `document.paragraphs` skips anything inside
  one, and resumes routinely put skills in a table, so the loss would have looked
  like a model that missed them. A `.docx` has no pages — Word decides that at
  render time — so it is reported as one page rather than having numbers invented
  for it. The upload gate now holds a signature per type (`%PDF-`, and `PK\x03\x04`
  for the zip a .docx is), so relabelling one as the other is still refused.
- **A latent repo bug, found by accident.** Checking a PDF fixture out during this
  work corrupted it: `core.autocrlf=true` (the Git-for-Windows default) plus no
  `.gitattributes` meant checkout rewrote 0x0A inside compressed streams.
  `resume_scanned.pdf` grew 35214 → 35293 bytes and stopped parsing. Verified by
  cloning the previous commit with `autocrlf=true` — the scan test fails on a clone
  where the code is fine — and re-verified fixed on current main. **This made
  "git clone && pytest -q works" false on a default Windows install**, and it would
  have read as a parser bug. Fixed with a `.gitattributes` marking binaries.

### Next, in order

1. **Push and watch CI** — small batches, per the standing advice below. Six
   commits are waiting.
2. **M2 #6 — the two-column fix** (the strict xfail in `test_parse.py` defines
   done, and the bboxes are cleanly separable — the left column ends at x≈154 and
   the right starts at x=300 in the fixture), then MinIO (#7). That closes M2.
3. **Decide on OCR confidence gating** — see the degradation findings below. It is
   the one open question the OCR work leaves behind.

### Worth knowing

- **The fixtures OCR perfectly, so they prove less than they look like they do.**
  Rather than leave that as a caveat, `resume_scanned.pdf` was degraded sixteen ways
  and scored by how many known lines still resolve as evidence. Full table in
  `HANDOFF.md` §7; the short version:
  - **Rotation is the only steep, common cliff.** 2° perfect → 5° loses a line →
    8° collapses → 12° fails outright. A phone photo is rotated far more often than
    it is blurred, so **deskew is the one preprocessing step with evidence behind
    it**. Everything else stays out.
  - Contrast, brightness, JPEG down to quality 3, and heavy speckle had **no
    measurable effect at all**. Tesseract 5 is much tougher than expected.
  - **The dangerous failure is not failure.** At 6px blur the page yields 169
    characters of confident nonsense — "Somchai Jaidee" becomes "Sore hector" —
    which sails past `MIN_CHARS_PER_TEXT_PAGE`, so the resume is reported as
    successfully read. Fabrication is still impossible (a quote must be located in
    that text) and the banner still says the page was OCR'd, but a character count
    cannot tell text from noise. Reading Tesseract's per-word confidence and
    rejecting a page below a threshold is what would close it — **not done**, and
    worth a decision rather than a silent default.
- **The experiment paid for itself immediately**: it surfaced that Tesseract emits
  **CRLF** on Windows while pdfplumber emits LF, so a part-scanned document carried
  both in one `document_text` and the same scan would have produced different
  offsets on Linux. One-line fix in the engine, pinned by two cases in the opt-in
  module. Nothing in the clean-fixture tests could have shown that.
- **OCR costs about a second per page** at 300 dpi, capped at `OCR_MAX_PAGES=10`.
  Parsing now runs in `asyncio.to_thread`, so it no longer blocks the worker's event
  loop or the progress streams the API is serving.

---

## 2026-08-08 — the browser walkthrough, finally

The Chrome extension connected, so the one thing outstanding since 2026-07-30 is
done. Full journey in a real browser, written into `HANDOFF.md` §1:

- **Live Gemini**: the line under the upload form moved "Uploading…" → "Parsing
  and verifying evidence…" → the profile, 10/10 claims verified. Clicking a
  citation highlighted it in the document pane and left the others dimmer.
- **The retry path**: with the worker started as
  `LLM_PROVIDER=fake FAKE_MODE=unavailable`, the page read "Attempt 1 failed,
  retrying — LLMUnavailableError: …", then "Attempt 2 failed…", then the amber
  "Stopped after 3 attempts" bar with "Try again" and the reason spelled out — and
  the parsed document still shown beside it, which is the failure path committing
  what it had. A healthy worker plus one click on "Try again" reached `extracted`
  with 12/12 claims.

That second sequence is what M2 #3 was for: before it, all of that was one
unchanging "Parsing and verifying evidence…".

### Worth knowing next time

- **The extension pairs per browser.** `list_connected_browsers` showed one
  device; the walkthrough needed it selected before any page action would run.
- **Authentication for a walkthrough does not need the form.** Registering the
  throwaway account over the API and writing `hirelens.access_token` /
  `hirelens.refresh_token` into `localStorage` skips typing a password into a
  browser and lands straight on the part actually under test.
- **The zombie API on :8000 is still there** and still serves pre-SSE code. This
  session ran on 8001 with `NEXT_PUBLIC_API_BASE=http://localhost:8001`. Reboot
  when convenient.

---

## 2026-08-07 (later) — pushed to CI, and M2 #3 lands

### What was done

- **The nine unpushed commits went to `origin/main` and CI is green on them.**
  The Postgres cutover, the ARQ worker, the retry/dead-letter policy and the §11
  fixes have now been built on a clean machine with no `.env`, no Docker and no
  API key. That was the largest outstanding process risk and it is closed.
- **M2 #3: `GET /resumes/{id}/events`**, a server-sent progress stream. It sends
  the resume on connect and again on every change, then `done` when it settles.
  The client (`waitForProfile` in `web/lib/api.ts`) opens it with `fetch` and
  reads frames off the `ReadableStream`, keeping the old polling loop as the
  fallback. The waiting message is now written from live state, so a user can
  finally see "attempt 1 failed, retrying" instead of one static line.
- Suite grew 164 → 173 (`tests/test_events.py`). All gates green: `pytest -q`,
  `ruff check`, `ruff format --check`, `mypy app`, and `npm run typecheck / lint /
  build`, plus `tests/test_postgres.py` (4 passed) against the real database.
- Two commits, both pushed and green: `60255a0` (the slice) and `617523a` (the
  live verification written into `HANDOFF.md` §1).

### The two decisions inside it

- **The stream is the contract; re-reading the row is only the mechanism.** The
  worker could publish to Redis and the endpoint could subscribe, but that puts
  Redis on the API's critical path and breaks the no-server default the inline
  queue and the whole test suite depend on. Nothing a client sees would change,
  so the cheap version is the one worth having.
- **`fetch`, not `EventSource`.** `EventSource` cannot set an `Authorization`
  header, and a token in the query string lands in proxy logs and browser
  history. ~30 lines of frame parsing buys the bearer header back.

### Verified live, against Postgres + Redis + the ARQ worker

Not just tests. Two runs, both in §1 of `HANDOFF.md`:

- **Live Gemini**: upload → `processing` → `extracted` → `done` over one
  connection, 10/10 claims verified, every match tier-1 exact.
- **The retry policy, watched rather than inferred**: with the provider forced
  down, the stream reported attempt 1 failing at +0.6 s, attempt 2 at +5.8 s and
  the dead letter at +16.1 s — the 5 s and 10 s backoffs, visible as they
  happened, each with its reason. `POST /retry` then reached `extracted` on
  attempt 4 with 12/12 claims verified, reusing the text parsed before the first
  failure.

That second run is the case the feature exists for, and it is now the clearest
demonstration the project has that the job layer works.

### Next, in order

1. **The browser walkthrough** — the rendering is the only part still unchecked:
   the waiting message, citation highlighting, and "Try again" as a user meets
   them. Blocked twice now on the Claude Chrome extension not being connected;
   everything behind the UI is verified at the HTTP level.
2. **M2 #4 — OCR fallback for scans** (Tesseract + `tha`), then DOCX (#5), the
   two-column fix (#6), MinIO (#7). `PLAN.md` has the order and the reasons.

### Two facts that shaped the code, not preferences

- **FastAPI closes `yield` dependencies before a streaming body runs** (since
  0.106; this repo is on 0.141). A `StreamingResponse` generator cannot use the
  request's session — it is already gone. That is why `app.state.sessionmaker`
  exists and the stream opens a short session per read. It also means an idle
  stream holds no pooled connection, which is the better shape anyway.
- **httpx's ASGI transport buffers a whole response** before handing it back, so
  `client.stream(...)` in a test does not deliver frames as they are written.
  `tests/test_events.py` therefore tests the endpoint over HTTP only where the
  stream ends by itself, and drives `_resume_events` directly for the sequence —
  the more deterministic test anyway, since the job runs to completion between
  two `anext` calls instead of racing the stream.

### Improvements to make / things to watch

- ~~**`web/` has no test framework at all.**~~ `readFrames` in `lib/api.ts` parses a
  wire format and buffers across chunk boundaries — the first real logic on that
  side, and nothing pinned it. — **fixed 2026-08-08**: vitest, nine cases in
  `lib/api.test.ts`, wired into CI between `lint` and `build`.
- ~~**`ALLOWED_ORIGINS` in `app/main.py` is a hard-coded list.**~~ It cost time this
  session: the Next dev server landed on :3001 because :3000 was taken, and every
  API call from it would have been blocked with a CORS error that says nothing
  about the real cause. — **fixed 2026-08-08**: it is now the `CORS_ORIGINS`
  setting, comma-separated.
- **A state shorter than `SSE_POLL_SECONDS` is not streamed.** The live retry run
  showed it: each failure was so fast that `processing` came and went inside one
  0.5 s read. Every resting state and every reason still arrived, which is what
  the UI shows — but do not read the stream as a complete history.
- ~~**`api/app/workers/` is an empty leftover package**~~ (a 0-byte `__init__.py`);
  the real module is `app/worker.py`. — **deleted 2026-08-08**.
- ~~The Chrome extension has blocked the browser walkthrough twice~~ — connected
  on 2026-08-08 and the walkthrough is done; see the entry above.
- **The machine had two stale dev servers** when this session started: a broken
  Next dev server on :3000 answering 500, and an API on :8000 still serving
  pre-SSE code whose process is gone while the socket keeps answering — a zombie
  no `Stop-Process` can reach. The session ran on fresh ports (API 8001, web 3000
  with `NEXT_PUBLIC_API_BASE=http://localhost:8001`) and stopped them at the end,
  so **only Docker is left running**. **Reboot, or at least check what is
  listening on :8000, before the next manual walkthrough** — otherwise it will
  quietly exercise old code.
- Still open from the previous entry and still true: the missing malformed-PDF
  fixture, the visibility timeout for a worker that dies mid-job (M5), cost
  figures reading `$0.000000` on Gemini's free tier, and statuses stored as enum
  *names* in raw SQL.

### Advice for the owner, for the rest of the project

- **The small-batch push worked — keep it.** Nine commits sat unpushed for a week
  and CI had never seen any of them; this session pushed twice and had an answer
  within a minute each time. One slice, one push, one CI result. The cost of a
  broken batch grows with the batch.
- **Before trusting any manual check, prove you are testing what you just
  built.** The zombie on :8000 answered `/health` perfectly while serving code
  from before the feature existed — a browser walkthrough against it would have
  "failed" for reasons that had nothing to do with the code. One `curl
  /openapi.json | grep <the-route-you-added>` first, every time.
- **Use env vars rather than editing `.env` for demos.**
  `LLM_PROVIDER=fake FAKE_MODE=unavailable arq app.worker.WorkerSettings` beats
  the real provider from the environment, leaves the file holding the real key
  untouched, and has nothing to restore afterwards. Stop the other workers first,
  or a healthy one takes the job.
- **Record the retry demo once the extension works.** A stream narrating attempt
  1 → attempt 2 → dead letter → "Try again" → verified profile is the single best
  thing this project has for showing that the job layer is real, and it is a
  twenty-second recording. Do it before M3 makes the UI busier.
- **Watch the Gemini free-tier quota** — the re-ask loop can spend 2× calls per
  resume and retries multiply that. If uploads start dead-lettering with provider
  errors, check quota before debugging code.
- **Guard the scope lines.** The baseline-ranking evaluation stays in M6 with its
  one-week timebox; the strict two-column xfail stays until column detection makes
  it pass; `LLM_PROVIDER=anthropic` stays an error until a live verification run.
  These hold only if they are not quietly renegotiated mid-milestone.
- **Keep real resumes out of the repo.** Testing with real documents locally is
  fine — they live in `var/uploads` and the dev database, and both should be wiped
  before the machine is shared or the project is demoed. PDPA work lands in M4.

---

## 2026-08-07 — the three §11 bugs are fixed and verified

### What was done

Commit `669e793` (one slice: fixes + tests + docs). Full write-up: `HANDOFF.md` §11.

- **Bug 1** — `_assemble` now strips `U+0000` where it already NFC-normalizes,
  before page spans are measured, so parser output is storable on Postgres and
  no evidence offsets shift.
- **Bug 2** — the success commit in `run_resume_job` moved inside the retry
  policy's `try`; a failing commit now retries and dead-letters instead of
  stranding the resume at `processing`.
- **Bug 3** — unexpected errors are recorded and logged by **type name only**
  (`_describe` in `app/jobs.py`), so a `DBAPIError` can no longer carry
  `document_text` into the log, `failure_reason` or the API.
- Suite grew 159 → 164 tests (plus a NUL round-trip in the opt-in Postgres
  module). All gates green: `pytest -q`, `ruff check`, `ruff format --check`,
  `mypy app`.
- The stranded row (`68d212a0-…`) was reset by hand and replayed through the
  fixed worker against live Gemini: `extracted` on attempt 2, 9/9 citations
  resolving exactly, no NUL stored, no PII in the worker log.

### Next, in order

1. **Push the local commits and watch CI.** CI has never run against the
   Postgres cutover, the ARQ worker, or these fixes. This is the cheapest
   outstanding risk reduction there is.
2. **Re-do the browser walkthrough** (register → upload → poll → profile, plus
   a forced failure → "Try again"). The polling loop and the retry button have
   only ever been verified at the HTTP level, never in a browser.
3. **M2 #3 — SSE progress endpoint**, replacing `waitForProfile` in
   `web/lib/api.ts`. Then, per `PLAN.md`: OCR (#4) → DOCX (#5) → two-column
   fix (#6) → MinIO (#7).

### Improvements to make / things to watch

- **One PII loose end from the incident:** the *pre-fix* worker terminal output
  from 2026-08-07 contained real resume text in the `DBAPIError` message. If
  that terminal's scrollback or any saved log file still exists, clear it. The
  code can no longer reproduce this, but the old output is still what it was.
- **A deliberately malformed PDF fixture is still missing.** The NUL case is
  pinned at the `_assemble` seam, but a real broken-ToUnicode PDF in
  `tests/fixtures/` would cover the road to it. Cheap to attempt next time
  `generate.py` is touched.
- **A worker killed mid-job can still strand a row at `processing`.** Bug 2's
  fix covers a commit that fails, not a process that dies. The visibility
  timeout is scheduled with M5 observability — do not forget it exists, and if
  a resume ever sits at `processing` with an old `last_attempt_at`, that is
  what happened.
- **Cost figures currently read `$0.000000`** because Gemini's free tier is
  priced at zero in the adapter. The moment a paid tier or a new provider
  lands, the price table must land with it (hard rule in `CLAUDE.md`), or every
  cost number in `llm_call_logs` silently becomes fiction.
- **Statuses are stored as enum *names*** (`DEAD_LETTERED`, not
  `dead_lettered`). Every raw SQL query against `resumes.status` must use the
  upper-case form — this bit the manual reset today and will bite again.

### Advice for the owner, for the rest of the project

- **Push in small, frequent batches.** A week of verified-but-unpushed commits
  is the current largest process risk: green locally means little until CI — a
  clean machine with no `.env`, no Docker and no key — agrees.
- **Run the definition-of-done gate before every commit**, from `api/` in the
  venv: `pytest -q && ruff check app tests migrations && ruff format --check
  app tests migrations && mypy app` (plus `npm run typecheck && npm run lint`
  when `web/` changed). Today's bugs were invisible to the gate; that is
  exactly why everything the gate *can* see must stay green.
- **After touching any pipeline seam, do one live run**, not only tests:
  `python -m app.cli tests/fixtures/resume_th.pdf` is 30 seconds, and the
  whole §11 incident was found by a live run the tests could not see.
- **Feed it ugly PDFs on purpose.** Every real-world template you can find
  (designer tools, Canva, Word exports) is a free fuzz test. Upload them
  against Postgres + the worker, not SQLite + inline — the incident only
  reproduced on the real stack.
- **Keep real resumes out of the repo and out of `.env`-adjacent places.**
  Testing with real documents is fine locally, but they are PII: they live in
  `var/uploads` and the dev database only, and both should be wiped before the
  machine is shared or the project is demoed. PDPA work lands properly in M4.
- **Guard the scope lines that already exist.** The baseline-ranking
  evaluation stays in M6 with its one-week timebox; the strict two-column
  xfail stays until column detection makes it pass; `LLM_PROVIDER=anthropic`
  stays an error until a live verification run. These are all decisions that
  hold up only if they are not quietly renegotiated mid-milestone.
- **Watch the Gemini free-tier quota.** The extraction re-ask loop can spend
  2× calls per resume, and retries multiply that. If uploads start
  dead-lettering with provider errors, check the quota before debugging code.
