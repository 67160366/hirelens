# Working notes

Short, dated notes from working sessions: what happened, what comes next, and
advice for the owner. Newest entry first. The detailed records stay in
`HANDOFF.md` and `PLAN.md` — this file is the quick version, with pointers.

---

## 2026-08-08 (latest) — the whole stack runs in containers

Driven by a course deliverable ("REST API + Docker & Docker Compose จัดการ
container"), which turned out to want the one thing the project genuinely lacked:
`docker-compose.yml` managed only postgres/redis/minio, while the API, the worker
and the web client all ran on the host by hand — **and the repository had no
Dockerfile at all**. That is M5's "containerize API + web", pulled forward.

`docker compose up -d --build` on a fresh clone now brings up seven services and
needs no Python, Node or Tesseract on the host.

### The decisions inside it

- **One image for the API and the worker, two commands.** `app/worker.py` is a thin
  adapter over `app/jobs.py`; two images would let their dependencies drift apart
  with nothing to catch it.
- **Migrations are their own one-shot service**, gated on `postgres` being healthy,
  with `api` and `worker` gated on it having *completed*. Running `alembic upgrade
  head` from an entrypoint instead would have two replicas racing on the same
  database.
- **Tesseract with `tha`+`eng` is installed in the API image.** The `OCR_COMMAND`
  full-path quirk (HANDOFF §8) exists because this machine's Tesseract is portable
  and off PATH; inside the image it is just `tesseract`. Still `OCR_ENGINE=none` by
  default — the rule was never "OCR is hard to install", it was "a scan must fail
  loudly rather than depend on a hidden default".
- **`.env` is read by compose on the host and passed in as environment; it never
  enters an image.** It holds a real Gemini key.
- **`NEXT_PUBLIC_API_BASE` is a build argument, not an environment variable.** Next
  inlines `NEXT_PUBLIC_*` at build time, so setting it under `environment:` would do
  exactly nothing. It also has to be an address a *browser* can reach —
  `http://api:8000` resolves between services and fails in every browser.

Also added **`POST /auth/change-password`**, the one genuinely missing auth feature.
Deliberately *not* added: `GET /users` (letting one candidate enumerate others is a
vulnerability, not a feature — RBAC/PDPA is M4), `POST /logout` (meaningless on
stateless JWTs without a denylist, and an endpoint that returns 200 while revoking
nothing is worse than none), and a username-availability check (an
account-enumeration oracle, which `/auth/login`'s single error message exists to
avoid).

### Verified live, not only by tests

Against the containers, with Postgres + Redis + the ARQ worker + **real Gemini**:

- `/openapi.json` lists `/auth/change-password` — proof the container serves the
  code just written, per the standing rule about zombie servers.
- Full auth journey: register → login → me → change-password → the old password is
  refused 401 → the new one logs in → a wrong current password is refused 403.
- `resume_th.pdf`: upload answered `pending` in **14 ms**, worker finished in 7.9 s,
  **10/10 verified, 0 dropped**, every match tier-1 exact, **10/10 spans slicing back
  out of `document_text`**.
- `resume_scanned.pdf`: `extracted` with **`pages_from_ocr=[1]`**, 7/7 verified, 7/7
  spans exact — the Tesseract *in the image* read it, Thai included.
- The worker log shows `worker started: provider=gemini storage=local ocr=tesseract`
  and arq taking the job, so the work really left the request. No PII in the log:
  ids, counts and durations only.
- CORS preflight from `http://localhost:3000` returns the origin back.
- The web bundle contains `localhost:8000` and **not** `http://api:8000`.

Suite: **209 → 214 passing** (the five new `TestChangePassword` cases), 12 skipped,
1 xfail still deliberate.

### One defect found and fixed during the work

**The worker inherited the API's healthcheck.** Same image, so `docker compose ps`
would have reported the worker permanently unhealthy for probing an HTTP server it
does not run — a false alarm that teaches people to ignore the one command that
tells them the stack is broken. Fixed with `healthcheck: disable: true` on that
service. Worth noting because it is invisible until you actually read `ps` output;
`up -d` reports success either way.

### Still open

1. **M2 #6 — the two-column fix.** Unchanged: the strict xfail defines done, and the
   bboxes are cleanly separable (left ends x≈154, right starts x=300).
2. **M2 #7 — MinIO.** `build_storage` still raises. The container is up and now the
   API runs beside it on the same network, so this got slightly easier.
3. Everything in the previous entry's watch list still stands.

---

## 2026-08-08 (later) — M2 #4 and #5, plus a repo bug that had been there all along

Seven commits, **pushed and green on CI** (run `31212427540`). A scan and a `.docx`
are both readable now, and M2 has only the two-column fix and MinIO left.

| | Commit |
|---|---|
| `23b3d1e` | Recover scanned pages with OCR before offsets are measured |
| `1a7f9b8` | Make the CORS allowlist a setting and drop the dead workers package |
| `82bc00a` | Pin the SSE frame parser with vitest |
| `f3d5348` | Normalize OCR line endings, and measure where OCR actually breaks |
| `e5bfaa3` | Mark binary fixtures binary, so a fresh clone can still read them |
| `4433c7d` | Read .docx resumes, tables included |

Suite: **173 → 209 passing** (12 skipped: 4 Postgres + 8 Tesseract, both opt-in),
1 xfail still deliberate. `web/` went from **no tests at all to 9**.

---

### What was done

**M2 #4 — OCR.** `OCR_ENGINE=tesseract` turns a scanned resume from a permanent
`failed` into a normal, fully cited profile. Tesseract 5.5.3 installed this session
with `eng`, `tha`, `osd`.

- `app/pipeline/ocr.py` is the seam: an `OCREngine` ABC, `TesseractEngine` driven
  over stdin/stdout, and `build_ocr_engine`. A subprocess rather than a wrapper
  library — no new Python dependency, and the page image never touches disk, which
  matters because it is a picture of somebody's resume.
- **`parse.py` substitutes recognized text before `_assemble` measures spans.** That
  one decision is why nothing downstream changed: evidence offsets, page mapping and
  `DocumentPane` highlighting all kept working untouched. Same move as the NUL strip
  from the §11 incident.
- Off by default, so CI and a fresh clone are unchanged. The suite drives the whole
  path through a stub engine; `tests/test_ocr_tesseract.py` is opt-in on
  `OCR_TESSERACT_CMD`, shaped like `tests/test_postgres.py`.
- `pages_from_ocr` on the resume (migration `0003`), in the API, and in the UI —
  because a citation into an OCR'd page is faithful to what was *read*, not to what
  was printed.

**M2 #5 — DOCX.** `parse_docx` reads paragraphs *and tables* in document order.
Tables are the whole point: `document.paragraphs` skips anything inside one, and
resumes routinely put skills in a table, so the loss would have looked like a model
that missed them. A `.docx` has no pages — Word decides that at render time — so it
is reported as one page rather than having numbers invented for it. The upload gate
now holds a signature per type (`%PDF-`, and `PK\x03\x04` for the zip a .docx is).

**Two items off the long-standing list**, both because they stopped being cosmetic:
`CORS_ORIGINS` is a setting now (it was blocking the browser check), the empty
`app/workers/` package is gone, and vitest pins `readFrames` with nine cases wired
into CI.

### Verified live, not only by tests

- **`resume_scanned.pdf`** through Postgres + ARQ + real Gemini: `pending` →
  `processing` → `extracted` in 5.7 s with `pages_from_ocr=[1]`. 7/7 verified,
  0 dropped, every match tier-1 exact, all 7 spans slicing back out of the stored
  text. **Three skills were cited straight out of the Thai OCR line**
  `ทักษะ: Python, FastAPI, PostgreSQL`.
- **`resume_mixed_scan.pdf`**: page 1 kept its text layer, page 2 came from the
  image, 5/5 verified.
- **In a browser** at :3002 — the amber banner reads "Page 1 had no text layer and
  was read by OCR. Quotes from it match what was recognized, which may differ from
  what was printed", `7/7 claims verified`, and the document pane carries six
  highlights over the recognized text, two inside the Thai line.
- **`resume_th.docx`** via `python -m app.cli`: 7/7 verified, all exact, Thai and
  table cells cited.
- Migration `0003` round-tripped on real Postgres; `pages_from_ocr` is real `jsonb`
  and `alembic check` reports no drift.

---

### Bugs found this session

**1. Binary fixtures were corrupted by `git checkout` on Windows.** The important
one, and it had been latent since the fixtures were committed.

`core.autocrlf=true` is the Git-for-Windows default, and with no `.gitattributes`
Git guessed the PDF fixtures were text. A `0x0A` inside a compressed stream became
`0x0D 0x0A` on checkout, and the xref offsets stopped pointing where they claim.
Measured on a fresh `git -c core.autocrlf=true clone` of the previous commit:

| | on disk | in repo |
|---|---|---|
| `resume_scanned.pdf` | 35293 | 35214 |
| `empty.pdf` | 1376 | 1308 |

`test_image_only_pdf_reports_a_scan` fails on that clone, and several OCR, API and
retry tests lean on the same fixture. **That made "`git clone && pytest -q` works
with no servers" false on a default Windows install** — a property `HANDOFF.md` §2
calls load-bearing — and the symptom reads as a parser bug, not a checkout bug.
Fixed by `.gitattributes` marking binaries; a fresh clone of current main gives
35214 and 1308 back and the parse and OCR suites are green.

*Method note worth keeping:* `git hash-object` said the file was fine, because it
re-normalizes while hashing. **Compare sizes, not hashes, when checking for CRLF
damage.** The first two attempts at this diagnosis were wrong for that reason.

**2. OCR and pdfplumber disagreed about line endings.** Tesseract ends lines with
CRLF on Windows and LF elsewhere; pdfplumber emits LF. So a part-scanned document
carried *both* conventions in one `document_text`, and the same scan would have
produced different evidence offsets depending on the machine that read it. One-line
fix in the engine (before `_assemble`, so no offset moved), pinned by two cases in
the opt-in module. Found only because of the degradation experiment — nothing in the
clean-fixture tests could have shown it.

**3. A stale ARQ worker silently stole the first live run.** A worker left running
from the previous session, on pre-OCR code, was still polling the same Redis queue.
It grabbed the job and marked the scan `failed`. The symptom is indistinguishable
from "the new code does not work"; the giveaway was the *wording* of
`failure_reason` in the database, which was the old message. Cost ten minutes.

**4. Not a bug, but recorded because it will look like one:** `npm audit` reports 3
high-severity advisories in `web/` production dependencies — `postcss` and `sharp`,
both transitive through Next 15. Pre-existing, unrelated to anything added here, and
they need a Next upgrade rather than a local fix.

---

### Still open, in order

1. ~~Push and watch CI.~~ **Done** — all seven commits are green on run
   `31212427540`. The number worth noticing: **209 passed, 12 skipped** on a runner
   with no Tesseract, no database and no API key. The opt-in split is doing exactly
   what it was built for, and OCR added a system dependency without costing the
   project its "clone and run" property.
2. **M2 #6 — the two-column fix.** The strict xfail in `test_parse.py` defines done.
   The bboxes are cleanly separable: in the fixture the left column ends at x≈154 and
   the right starts at x=300. This also produces the geometry the true pdf.js overlay
   (#8) needs.
3. **M2 #7 — MinIO.** `build_storage` has the branch stubbed and the container is
   already running. That closes M2.
4. **Decide on OCR confidence gating** — the one open question the OCR work leaves
   behind. See below.

### Things to watch, and to improve

- **A badly degraded scan does not fail — it succeeds with nonsense.** This is the
  most important thing to understand about the OCR feature. At 6px blur the page
  still yields 169 characters, well past `MIN_CHARS_PER_TEXT_PAGE`, so the resume is
  reported as read: "Somchai Jaidee" comes back as "Sore hector". Fabrication is
  still impossible — a quote must be located in that text — and the banner still
  says the page was OCR'd, but **a character count cannot tell text from noise**.
  Reading Tesseract's per-word confidence and rejecting a page below a threshold is
  what would close it. Deliberately **not done**: it is a product decision about how
  much to trust a bad scan, and it deserves a choice rather than a silent default.
- **Rotation is the only steep, common failure.** 2° is perfect, 5° loses a line, 8°
  collapses to 1/5, 12° fails outright. Contrast, brightness, JPEG down to quality 3
  and heavy speckle had *no measurable effect*. So preprocessing stays out except
  that **deskew now has evidence behind it** rather than being a guess — a phone
  photo is rotated far more often than it is blurred. Full table in `HANDOFF.md` §7.
- **The fixtures OCR perfectly, which makes them prove less than they look like they
  do.** They are synthetic renders of known text. No test in this repo can show what
  a real photographed resume does.
- **OCR costs about a second per page** at 300 dpi, capped by `OCR_MAX_PAGES=10`.
  Parsing now runs in `asyncio.to_thread`, so it no longer blocks the worker's event
  loop or the progress streams the API is serving.
- **The zombie API on :8000 and the dev server on :3000 are still there**, unchanged
  from the previous entry. All ARQ workers are stopped — start one when you next need
  it. Still worth a reboot.
- **CI warns that `actions/checkout@v4` and `astral-sh/setup-uv@v5` target Node 20**,
  which GitHub has deprecated and is force-running on Node 24. Harmless today, a
  broken build whenever they drop the shim. Bumping both to their v5/v6 majors is a
  two-line change worth doing before it becomes urgent.
- Still open from previous entries: the missing malformed-PDF fixture, the visibility
  timeout for a worker that dies mid-job (M5), cost figures reading `$0.000000` on
  Gemini's free tier, and statuses stored as enum *names* in raw SQL.

### Advice for the owner, for the rest of the project

- **Before believing any live run, prove three things:** that the server you are
  hitting has the code you just wrote (`curl /openapi.json | grep <new-field>`), that
  no *other* worker is competing for the queue
  (`Get-CimInstance Win32_Process | Where CommandLine -like '*arq*'`), and that you
  are on the port you think you are. Two of the three bit this session. The stale
  worker is the nastiest, because a wrong result looks exactly like a code bug.
- **Do the cleanup when it starts blocking you, not before and not never.**
  `ALLOWED_ORIGINS` sat on the "should fix" list for two sessions as a nice-to-have.
  It was fixed the moment it stood between finished work and its verification — and
  that turned out to be the right trigger. A cleanup that blocks verification is not
  cosmetic any more.
- **Write the experiment instead of the caveat.** "Real scans will be worse than the
  fixtures" was a true, useless sentence. Two hours of degrading images turned it
  into a table with numbers, a preprocessing decision with evidence behind it, and a
  real bug (the CRLF one) that no amount of caveat-writing would have found.
- **When a check says "everything is fine", ask what instrument you used.**
  `git hash-object` reported the corrupted PDFs as intact because it normalizes while
  hashing. The tool was answering a different question than the one being asked.
- **Keep pushing in small batches.** Six commits are unpushed right now; that is
  already at the edge of comfortable. Green locally means little until a clean
  machine with no `.env`, no Docker and no key agrees.
- **Feed it ugly documents on purpose** — real scans, phone photos, Canva exports,
  Word files with tables. Every one is a free fuzz test, and every real defect this
  project has found came from a real document rather than from a test.
- **Guard the scope lines.** The baseline-ranking evaluation stays in M6 with its
  one-week timebox; the strict two-column xfail stays until column detection makes it
  pass; `LLM_PROVIDER=anthropic` stays an error until a live verification run. These
  hold only if they are not quietly renegotiated mid-milestone.
- **Watch the Gemini free-tier quota.** The re-ask loop can spend 2× calls per resume
  and retries multiply that. If uploads start dead-lettering with provider errors,
  check quota before debugging code.
- **Keep real resumes out of the repo.** Testing with real documents locally is fine
  — they live in `var/uploads` and the dev database, and both should be wiped before
  the machine is shared or the project is demoed. PDPA work lands in M4.

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
