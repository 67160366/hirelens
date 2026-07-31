# Handoff — end of M1

Written 2026-07-30. Read this first when picking the project back up.

---

## 1. Where things stand

**M1 is complete and verified end-to-end.** Upload a PDF resume → get back a profile
in which every field cites the exact text it came from, and anything the model could
not cite is dropped and reported.

Verified by actually running it, not just by tests:

| Check | Result |
|---|---|
| `pytest -q` | 111 passed, 1 xfailed (the xfail is deliberate — see §5) |
| `ruff check` / `ruff format --check` | clean |
| `mypy app` (strict) | clean, 31 files |
| Alembic `upgrade head` → `downgrade base` | round-trips |
| Browser: register → upload Thai PDF → read profile | works; 10/10 claims verified, all exact matches |
| Browser: same with `FAKE_MODE=hallucinating` | works; 12/13 verified, 7.7% unverifiable, fabricated claim excluded and reported |

**Nothing is committed yet.** Branch `main` has zero commits. Everything described
here is working-tree only.

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
| 10 | The plan file (see §7) | Milestones M2–M6 and the reasoning behind the scope calls |

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
  services/resume_service.py
  api/routes/          auth.py, resumes.py
  cli.py               `python -m app.cli <pdf>` — fastest way to see output
web/
  app/page.tsx         auth + upload + result
  components/Evidence.tsx, ProfileView.tsx
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
| Database | **SQLite** at `api/var/dev.db` (`.env` → `DATABASE_URL`). Postgres not used yet. |
| Docker | **Not installed.** `docker-compose.yml` is written and ready. |
| LLM provider | **`fake`.** No Gemini key has been used yet — the real provider path is written but has never made a live call. |
| Storage | Local filesystem at `var/uploads` |

### Start it

```bash
cd api
uvicorn app.main:app --reload      # http://127.0.0.1:8000  (/docs for OpenAPI)

cd ../web
npm run dev                        # http://localhost:3000
```

Fastest sanity check, no servers needed:

```bash
cd api && python -m app.cli tests/fixtures/resume_th.pdf
```

To see the dropped-claims path: set `FAKE_MODE=hallucinating` in `.env`, restart the
API, upload again.

---

## 7. Next steps

Three setup items first, in this order — each unblocks real work:

1. **Install Docker Desktop**, then `docker compose up -d` and switch
   `DATABASE_URL` in `.env` to the Postgres URL from `.env.example`. Re-run
   `alembic upgrade head`. This is worth doing before M2 because the worker needs
   Redis and OCR output belongs in MinIO. Verify the JSONB path works on real
   Postgres — the tests only prove the SQLite variant.
2. **Get a Gemini API key** (<https://aistudio.google.com/apikey>, free, no card),
   set `LLM_PROVIDER=gemini`, and run the CLI against every fixture. **Expect the
   first real run to surface problems the fake cannot** — that is the point of doing
   it early. Watch specifically for: quotes that fail verification because the model
   reformatted Thai, `response_schema` rejecting the `RawClaim | None` optionals, and
   `max_output_tokens` truncating mid-JSON. Record the hallucination rate you see;
   it is the project's headline number.
3. **Make the first commit.** Nothing is committed. Suggested split: scaffold +
   config, then evidence + parse (+ tests), then LLM seam, then API, then web, then
   CI + docs.

Then M2, in dependency order:

| # | Work | Notes |
|---|---|---|
| 1 | ARQ worker + Redis; move `process_resume` off the request | `resume_service.process_resume` was written to be called from a job — it takes no HTTP types and does not commit |
| 2 | Job state, retry with backoff, dead-letter queue | |
| 3 | SSE progress endpoint; wire the web UI's "Parsing…" state to it | |
| 4 | OCR fallback for scans (Tesseract + `tha`) | `ParsedDocument.pages_without_text` is already the work list; `resume_scanned.pdf` and `resume_mixed_scan.pdf` are real image-based fixtures ready for it |
| 5 | DOCX parser | `parse_document_bytes` already dispatches on extension and raises `UnsupportedFileTypeError` |
| 6 | **Two-column fix** via bbox column detection | Task #11. The xfail test defines "done" |
| 7 | MinIO storage backend | `build_storage` has the `MINIO` branch stubbed with a clear error |
| 8 | **PDF viewer with highlighted evidence spans** | The single most valuable UI piece for the portfolio. The API already returns `document_text` plus char offsets so no re-parsing is needed. |

M3 onward (matching engine, backend depth, frontend, ship) is in the milestone
plan, which is kept outside this repository.

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
