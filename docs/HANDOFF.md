# Handoff

Written 2026-07-30 at the end of M1; updated 2026-08-06 after the hardening pass
and the first live Gemini runs. Read this first when picking the project back up —
then `CLAUDE.md` for the rules and commands, and `docs/PLAN.md` for per-item
milestone status.

---

## 1. Where things stand

**M1 is complete and verified end-to-end.** Upload a PDF resume → get back a profile
in which every field cites the exact text it came from, and anything the model could
not cite is dropped and reported.

Verified by actually running it, not just by tests:

| Check | Result |
|---|---|
| `pytest -q` | 130 passed, 1 xfailed (the xfail is deliberate — see §5) |
| `ruff check` / `ruff format --check` | clean |
| `mypy app` (strict) | clean, 31 files |
| Alembic `upgrade head` → `downgrade base` | round-trips |
| Browser: register → upload Thai PDF → read profile | works; 10/10 claims verified, all exact matches |
| Browser: same with `FAKE_MODE=hallucinating` | works; 12/13 verified, 7.7% unverifiable, fabricated claim excluded and reported |
| CLI with `LLM_PROVIDER=gemini`, every fixture | 0% final hallucination rate, all matches tier-1 exact incl. Thai (2026-08-06 — see `docs/llm-providers.md`) |

**Committed and pushed.** `main` is on GitHub at
<https://github.com/67160366/hirelens> and CI is green — the workflow needed one
fix on its first real run, because `uv pip install --system` is refused on the
runner's PEP 668 system Python.

### Updated 2026-08-06 — what changed since the M1 handoff

- **Agent guidance now exists.** `CLAUDE.md` holds the rules, commands, and
  working style; `docs/PLAN.md` holds M1–M6 with per-item status (**M3–M6 are a
  draft awaiting the owner's review**); `.claude/settings.json` allowlists the
  routine check commands.
- **A hardening pass over the M1 seams**, each behaviour pinned by a test:
  logging throughout (ids and counters only — never document text), the
  duplicate-upload race resolves to the winner's row instead of a 500, a failed
  ingest deletes the blob it wrote, uploads are judged by `Content-Length` and
  `%PDF-` magic bytes, the API refuses to boot on the placeholder JWT secret
  outside `APP_ENV=dev`, and `POST /auth/refresh` rotates the token pair with the
  web client retrying once on 401 before signing out.
- **Dependencies are locked**: `api/uv.lock`, installed with `uv sync --locked`
  in CI, so builds stop resolving a fresh tree per run.
- **Gemini ran live for the first time** and broke exactly where §7 predicted:
  `gemini-2.5-flash` is 404 for keys created after mid-2026 (the default is now
  `gemini-3.6-flash`), and `response_schema` rejects the `additionalProperties`
  that `extra="forbid"` generates (the adapter now sends `response_json_schema`
  and validates the reply with Pydantic itself). Results and observations are in
  `docs/llm-providers.md`; the adapter contract is pinned by mocked tests in
  `api/tests/test_gemini.py`.
- The suite is hermetic against the developer's `.env` (which now selects the
  real provider) and grew from 111 to 130 tests.

---

## 2. The one idea, so the code makes sense

Models cannot count characters, so they are never asked to. The model returns only
a **quote**; the application locates that quote in the source document itself.

```
parse (keep char offsets) → ask the model for quotes → locate every quote → keep only what resolved
```

A quote that cannot be located is a fabrication. This single rule is why the
codebase is shaped the way it is, and it yields three things at once: a guardrail,
explainability (page + char range for the UI to highlight), and a hallucination rate
that costs nothing to produce — no labelled dataset, no baseline to beat.

**Do not weaken this.** If a change would let an unverified claim reach the
response, it is the wrong change.

---

## 3. Read these files first, in this order

Roughly 30 minutes to get oriented.

| Order | File | Why |
|---|---|---|
| 1 | `README.md` | The idea, quick start, honest limitations |
| 2 | **`api/app/pipeline/evidence.py`** | The heart of the project. Three-tier matching, offset maps, rejection reasons. Everything else serves this. |
| 3 | `api/tests/test_evidence.py` | The clearest specification of intended behaviour, including the Thai cases |
| 4 | `api/app/pipeline/parse.py` | The offset contract: `ParsedDocument.text` is the single coordinate space all evidence points into |
| 5 | `api/app/pipeline/extract.py` | How verification is enforced and how the retry loop picks a result |
| 6 | `api/app/schemas/extraction.py` + `profile.py` | The two-layer split: what the model returns (quotes only) vs what we store (offsets + stats) |
| 7 | `api/app/llm/fake.py` | Load-bearing infrastructure, not a stub — read before touching the provider seam |
| 8 | `api/app/services/resume_service.py` | Where storage, parsing, extraction and persistence meet |
| 9 | `docs/llm-providers.md` | Provider choice, `FAKE_MODE`, real cost figures |
| 10 | `docs/PLAN.md` | Milestones M2–M6 and the reasoning behind the scope calls |

Skim only when needed: `api/app/api/routes/*`, `api/app/security.py`,
`api/app/storage.py`, `web/*`.

---

## 4. What was built

```
api/app/
  pipeline/
    evidence.py      ★ locate quotes in the source; reject what cannot be found
    parse.py           PDF → text + char offsets + page spans; detects scans vs blank
    extract.py         orchestrates: ask → verify → retry → keep the cleanest result
    prompts.py         versioned prompts (EXTRACTION_PROMPT_VERSION)
  llm/
    base.py            StructuredExtractor interface, usage/cost types
    fake.py          ★ rule-based extractor over the real document + failure modes
    gemini.py          Gemini free tier via google-genai
    registry.py        provider selection from settings
  schemas/
    extraction.py      what the model returns — quotes only, no offsets
    profile.py         what we store — offsets, pages, stats, dropped claims
  models/core.py       candidates, resumes, extracted_profiles, llm_call_logs
  services/resume_service.py   upload path: store, insert, queue
  jobs.py              run_resume_job — the unit of background work, arq-free
  queue.py             JobQueue seam: inline (no server) / arq (Redis)
  worker.py            `arq app.worker.WorkerSettings`
  api/routes/          auth.py, resumes.py
  cli.py               `python -m app.cli <pdf>` — fastest way to see output
web/
  app/page.tsx         auth + upload + result
  components/Evidence.tsx, ProfileView.tsx, DocumentPane.tsx (citation highlighting)
```

Design decisions worth not re-litigating:

- **Profile stored as one JSON column, stats lifted into real columns.** The profile
  shape is still moving and M3 adds requirement-level tables anyway; normalizing
  twice would be wasted work. The counters are separate columns so cost and
  hallucination queries are plain SQL.
- **`JSON_VARIANT`** in `models/base.py` renders JSONB on Postgres, JSON on SQLite —
  which is what lets the whole test suite run without a database server.
- **The fake backend is the default provider.** A fresh clone runs every test with
  no API key and no spend, and CI never depends on a third party being up.
- **Client-generated UUID primary keys**, so a caller holds the id before commit.
- **`document_text` is stored verbatim on the resume row.** Evidence offsets index
  into exactly that string; re-parsing later could shift every citation already
  shown to a user.

---

## 5. Deliberate loose ends (not bugs — leave the shape intact)

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

---

## 6. Environment — read before running anything

**Project path must stay ASCII.** This machine's ANSI codepage is **cp874 (Thai)**.
The project originally lived at `D:\งาน\webapp_dev`, and an editable install
(`uv pip install -e .`) wrote a `.pth` file containing that path in UTF-8. Python's
`site` module reads `.pth` files using the system codepage, hit byte `0x87`, and the
interpreter died at startup — the venv became unusable. The project was moved to
`D:\work\webapp_dev` and the problem is gone. Do not move it back under a non-ASCII
path, and prefer ASCII paths for anything Docker will bind-mount.

`api/pyproject.toml` also sets `pythonpath = ["."]` for pytest, so the suite works
even without an editable install.

### Current state of the local stack

| Thing | State |
|---|---|
| Database | **Postgres** in Docker (`.env` → `DATABASE_URL`), migrated and verified 2026-08-07. SQLite at `api/var/dev.db` is kept as a commented fallback; the test suite still uses its own in-memory SQLite. |
| Docker | **Installed and running.** `docker compose up -d` brings up `postgres` (pgvector/pg17), `redis` and `minio`. Redis carries the job queue since M2 #1; MinIO is up but unused until M2 #7. |
| Queue | **`arq`** (`.env` → `QUEUE_BACKEND`). Run `arq app.worker.WorkerSettings` alongside the API, or set `inline` to process in-request with no Redis. |
| LLM provider | **`gemini`** (`gemini-3.6-flash`) in `.env`; live-verified against every fixture on 2026-08-06 — see `docs/llm-providers.md`. Tests and CI still run on `fake`. |
| Storage | Local filesystem at `var/uploads` |

### Start it

```bash
cd api
uvicorn app.main:app --reload      # http://127.0.0.1:8000  (/docs for OpenAPI)
arq app.worker.WorkerSettings      # a second terminal; only for QUEUE_BACKEND=arq

cd ../web
npm run dev                        # http://localhost:3000
```

Without the worker running, uploads sit at `pending` forever. Re-uploading the
same file re-queues it, so starting the worker late still gets the work done.

Fastest sanity check, no servers needed:

```bash
cd api && python -m app.cli tests/fixtures/resume_th.pdf
```

To see the dropped-claims path: set `FAKE_MODE=hallucinating` in `.env`, restart the
API, upload again.

---

## 7. Next steps

**The setup items are all done.** The code is pushed with CI green, the evidence
viewer (M2 #8 below) is built, the first live Gemini run happened on 2026-08-06 —
it surfaced two adapter problems, both fixed (see §1 and `docs/llm-providers.md`) —
and on 2026-08-07 development moved onto Postgres in Docker, with the JSONB path
verified for the first time (§6 and `docs/PLAN.md`).

M2 #1 landed the same day: parsing and extraction now run on an ARQ worker
instead of inside the upload request. **Next is M2 #2.** In dependency order
(live status in `docs/PLAN.md`):

| # | Work | Notes |
|---|---|---|
| 1 | ~~ARQ worker + Redis~~ **done** — `process_resume` runs off the request | `app/jobs.py` (the work), `app/queue.py` (inline/arq seam), `app/worker.py` (entrypoint). Upload answers `pending`; clients poll |
| 2 | Job state, retry with backoff, dead-letter queue | A failed job leaves the resume `pending` and arq's default retry applies; nothing records attempts yet. `_requeue_if_stalled` in `resume_service` is the stopgap that keeps re-upload from stranding work |
| 3 | SSE progress endpoint; wire the web UI's "Parsing…" state to it | The web client polls today — `api.waitForProfile` in `web/lib/api.ts` is the one place to replace |
| 4 | OCR fallback for scans (Tesseract + `tha`) | `ParsedDocument.pages_without_text` is already the work list; `resume_scanned.pdf` and `resume_mixed_scan.pdf` are real image-based fixtures ready for it |
| 5 | DOCX parser | `parse_document_bytes` already dispatches on extension and raises `UnsupportedFileTypeError` |
| 6 | **Two-column fix** via bbox column detection | Task #11. The xfail test defines "done" |
| 7 | MinIO storage backend | `build_storage` has the `MINIO` branch stubbed with a clear error |
| 8 | ~~Evidence viewer~~ **done** — text-layer only | `web/components/DocumentPane.tsx` highlights every citation in `document_text` and scrolls to the one clicked. A true pdf.js overlay on the rendered page is *not* done: it needs bbox geometry, which `ParsedDocument` does not keep, plus an endpoint serving the original file. Do it with #6, which needs the same bbox extraction. |

M3 onward (matching engine, backend depth, frontend, ship) is in
[`docs/PLAN.md`](PLAN.md), which also tracks the status of the items above.

---

## 8. Things to be careful about

- **Never let an unverified claim into a response.** Add to `dropped`, not to the
  profile.
- **Do not have the model produce offsets.** It is the mistake the whole design
  avoids.
- **`ruff format` is enforced in CI.** Run it before pushing.
- **Test data is synthetic and must stay that way.** No real person's resume goes in
  this repo. Regenerate fixtures with `python api/tests/fixtures/generate.py`
  (needs a Thai-capable font locally; the generated PDFs are committed so CI does
  not).
- **If you add a paid provider, update the price table** in the adapter. A stale
  price silently corrupts every cost figure.
- **Scope discipline on evaluation.** Ranking metrics against a BM25/embedding
  baseline are deliberately *out* of the critical path (M6, one-week timebox). The
  measurable-for-free metrics — hallucination rate, parse success, cost per
  document — are in. This was a considered decision to avoid unbounded work; don't
  quietly promote the baseline comparison into M2 or M3.
