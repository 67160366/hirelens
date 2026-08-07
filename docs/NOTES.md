# Working notes

Short, dated notes from working sessions: what happened, what comes next, and
advice for the owner. Newest entry first. The detailed records stay in
`HANDOFF.md` and `PLAN.md` — this file is the quick version, with pointers.

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
  build`.

### The two decisions inside it

- **The stream is the contract; re-reading the row is only the mechanism.** The
  worker could publish to Redis and the endpoint could subscribe, but that puts
  Redis on the API's critical path and breaks the no-server default the inline
  queue and the whole test suite depend on. Nothing a client sees would change,
  so the cheap version is the one worth having.
- **`fetch`, not `EventSource`.** `EventSource` cannot set an `Authorization`
  header, and a token in the query string lands in proxy logs and browser
  history. ~30 lines of frame parsing buys the bearer header back.

### Next, in order

1. **The browser walkthrough** — register → upload → watch the status narrate →
   profile → forced failure → "Try again". Still the one thing never checked in a
   real browser.
2. **M2 #4 — OCR fallback for scans** (Tesseract + `tha`), then DOCX (#5), the
   two-column fix (#6), MinIO (#7). `PLAN.md` has the order and the reasons.

### Worth knowing

- **httpx's ASGI transport buffers a whole response** before handing it back, so
  `client.stream(...)` in a test does not deliver frames as they are written.
  `tests/test_events.py` therefore tests the endpoint over HTTP only where the
  stream ends by itself, and drives `_resume_events` directly for the sequence —
  which is the more deterministic test anyway, since the job runs to completion
  between two `anext` calls instead of racing the stream.
- **FastAPI closes `yield` dependencies before a streaming body runs** (since
  0.106). A `StreamingResponse` generator cannot use the request's session, which
  is why `app.state.sessionmaker` exists and the stream opens a short session per
  read.
- The three stream timings are settings (`SSE_POLL_SECONDS`,
  `SSE_HEARTBEAT_SECONDS`, `SSE_MAX_STREAM_SECONDS`) because a proxy in front of
  the API may well need different ones.

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
