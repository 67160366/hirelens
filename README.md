# HireLens

Resume screening where **every claim the system makes cites the exact text it came
from** — and anything it cannot cite is dropped and reported rather than shown.

Built from the HR Tech user journey (#19) in `userjourneysthailand.md.pdf` — a
source document kept out of the repository (it may contain third-party content),
so a fresh clone will not have it. Its pain points name the problem directly: *"เรซูเม่ไม่ผ่านการคัดกรองอัตโนมัติ (ATS)
โดยไม่รู้สาเหตุ"* — candidates rejected by automated screening with no explanation.

Handles Thai and English resumes.

---

## The one idea

Models cannot count characters, so they are never asked to. The model returns only
a **quote**; the application locates that quote in the source document itself.

```
parse (keep char offsets) → ask the model for quotes → locate every quote → keep only what resolved
```

A quote that cannot be located is a fabrication. That single rule produces three
things at once:

1. **A guardrail.** Unverifiable claims never reach a reviewer.
2. **Explainability.** Every field carries a page number and character range, which
   is what the UI renders — highlighted in the extracted text, and from M5 boxed on
   the original PDF itself, from character positions measured at parse time rather
   than searched for afterwards.
3. **A metric, for free.** Counting rejected quotes gives a hallucination rate with
   no labelled dataset and no baseline to beat.

The implementation lives in [`api/app/pipeline/evidence.py`](api/app/pipeline/evidence.py).
Matching runs in three tiers — verbatim, then whitespace-insensitive, then
whitespace-stripped, the last mainly to rescue Thai, which PDF extraction likes to
break mid-word. The tier that matched is recorded, so a run full of loose matches
points at a parser problem rather than hiding one.

---

## Status

**M4 complete.** Upload a PDF, get back a profile in which every field is traceable
to the source — then post a job, and see every candidate ranked by requirements they
can be shown to meet, each verdict citing the line it rests on. Candidates apply, and
every move an application makes is recorded with who made it and what it rested on:
**you cannot shortlist somebody who has not been screened, and you cannot reject them
without a reason.**

| Milestone | Scope |
|---|---|
| **M1 ✅** | Parse (PDF, offsets, Thai), extract, verify evidence, retry on rejection, auth, upload API, web UI |
| **M2 ✅** | Async worker + queue, OCR for scans, DOCX, two-column layout fix, MinIO, evidence viewer |
| **M3 ✅** | Job requirements, retrieval, requirement-level judging, ranking, a screening UI |
| **M4 ✅** | Visibility timeout, RBAC, the application state machine, PDPA (export and erasure) |
| **M5 ✅** | Dropped-claims audit view, usage and quality dashboard, character geometry, pdf.js overlay, production compose and a runbook |
| M6 | **Reviewed and closed unbuilt** (2026-08-16) — the ranking evaluation could not be built as scoped. Reasons in [docs/PLAN.md](docs/PLAN.md) |

Picking the project up after a break: **[docs/HANDOFF.md](docs/HANDOFF.md)** — what
exists, which files to read in what order, and what to do next. The full milestone
plan with per-item status lives in [docs/PLAN.md](docs/PLAN.md).

---

## Quick start — everything in containers

Requires only Docker. No Python, Node or Tesseract on the host.

```bash
docker compose up -d --build
```

That builds two images and runs eight services: `postgres`, `redis`, `minio`, the
one-shot `createbucket` and `migrate`, then the `api`, the `worker` and the `web`
client.

| | |
|---|---|
| API | <http://localhost:8000> — OpenAPI at `/docs` |
| Web | <http://localhost:3000> |
| MinIO console | <http://localhost:9001> — holds uploads when `STORAGE_BACKEND=minio` |

```bash
docker compose ps          # api and web report healthy; migrate exits 0
docker compose logs -f worker
docker compose down        # add -v to discard the database and uploaded files
```

`api` and `worker` are **the same image with different commands** — `app/worker.py`
is a thin adapter over `app/jobs.py`, and building them separately would let their
dependencies drift apart unnoticed. Migrations run as their own service rather than
in the API's entrypoint, so two replicas cannot race to apply them.

Defaults need no API key: the stack comes up on the `fake` provider. Anything set
in `.env` is picked up by compose (`LLM_PROVIDER=gemini`, `OCR_ENGINE=tesseract`,
`GEMINI_API_KEY=…`) and passed to the containers as environment — **`.env` is never
copied into an image**. Tesseract with `tha`+`eng` is installed in the API image, so
OCR needs no path setting here, unlike on a host with a portable install.

### Running it on the host instead

```bash
cp .env.example .env          # defaults need no API key and no database server

cd api
uv venv --python 3.11
uv pip install -e ".[dev]"
alembic upgrade head          # SQLite by default; see .env for Postgres
uvicorn app.main:app --reload
arq app.worker.WorkerSettings # another terminal; only for QUEUE_BACKEND=arq

cd ../web
npm install
npm run dev                   # http://localhost:3000
```

The web app expects the API at `http://localhost:8000`; if it lives elsewhere, set
`NEXT_PUBLIC_API_BASE`. It is read at **build** time, so in Docker it is a build
argument — and it must be an address a *browser* can reach, never the compose
service name.

With `QUEUE_BACKEND=inline` (the host default) there is no worker and no Redis: the
upload request does the work itself. The API behaves the same either way — it
answers `pending` and the client follows the progress stream.

---

## REST API

Every route is authenticated except `/health` and the two credential endpoints, and
there are **two ways to present the same session**. A `Bearer` header is what every
`curl` here and in `docs/RUNBOOK.md` uses. The credential routes *also* set httpOnly
cookies, which is what the web client runs on — so a browser never holds a token
anywhere script can read it. Bearer wins when both are sent. Full schema at `/docs`.

| Method | Path | |
|---|---|---|
| `POST` | `/auth/register` | Create an account; returns an access + refresh pair **and** sets it as cookies. Always a **candidate** — `recruiter` and `admin` are granted out of band |
| `POST` | `/auth/login` | Exchange credentials for a token pair, in the body and in cookies |
| `POST` | `/auth/refresh` | Rotate the pair; the token presented is revoked, so it is genuinely single-use. The body is optional — a browser cannot read its own httpOnly cookie to send one, so the cookie is used instead |
| `POST` | `/auth/logout` | End this session — the access token, the refresh token behind it, and the cookies carrying them |
| `POST` | `/auth/change-password` | Prove the old password, set a new one |
| `GET` | `/auth/me` | The signed-in account, and its role |
| `GET` | `/auth/me/export` | Everything held about you, as one JSON document |
| `DELETE` | `/auth/me` | Erase the account. Stored files go before rows, and a file that will not delete abandons the whole thing |
| `GET` | `/resumes/consent` | What an upload's `consent` field agrees to. Unauthenticated |
| `POST` | `/resumes` | Upload a PDF or DOCX **with `consent=true`**; answers `pending` and queues the work |
| `GET` | `/resumes` | The caller's resumes |
| `GET` | `/resumes/{id}` | Profile, evidence spans and the text they index into |
| `GET` | `/resumes/{id}/events` | SSE progress stream until the status settles |
| `POST` | `/resumes/{id}/retry` | Replay a `dead_lettered` or `failed` resume |
| `POST` `GET` `PATCH` `DELETE` | `/jobs`, `/jobs/{id}` | Job postings |
| `POST` `GET` `PATCH` `DELETE` | `/jobs/{id}/requirements[/{rid}]` | What a candidate is judged against; nested so ownership is settled once |
| `POST` `GET` | `/jobs/{id}/screenings` | Judge a resume against the job. **202** when it queued work, **200** when the stored result already answers |
| `GET` | `/jobs/{id}/ranking` | Candidates ordered, each entry carrying its verdicts *and* their citations. No model call |
| `GET` | `/jobs/{id}/candidates` | Which resumes are worth paying to judge. A hint, never a gate — every resume is returned, ordered |
| `POST` `GET` | `/jobs/{id}/applications` | Apply to a job (**201** new / **200** already applied); the owner's list of who applied |
| `GET` | `/me/applications` | Everything you have applied for |
| `GET` `POST` | `/applications/{id}[/transitions]` | One application, and moving it. **409** with the reason when the move is not allowed |
| `GET` | `/applications/{id}/events` | The append-only log the state is derived from |
| `GET` | `/screenings/{id}` | One screening, with the text its citations index into |
| `POST` | `/screenings/{id}/retry` | Replay a stopped screening |
| `GET` | `/health` | Liveness, and which provider is active |

There is deliberately **no `/users` listing and no username check.** Resumes are PII, so
letting one account enumerate others is a vulnerability rather than a feature — RBAC
landed in M4, and so did the two PDPA rights the system can honour: a copy of your data,
and its erasure. Username checks are an account-enumeration oracle, which is exactly what
`/auth/login`'s single error message exists to avoid.

**`POST /auth/logout` exists as of 2026-08-16, and did not before.** The reason it was
absent is worth keeping: on stateless JWTs a logout route needs a denylist to mean
anything, and an endpoint that returns 200 without revoking anything is worse than not
having one. `revoked_tokens` is that denylist, so the route now actually ends the
session — both the access token and the refresh token behind it.

### Try it without the web app

```bash
cd api
python -m app.cli tests/fixtures/resume_th.pdf
```

```
Name       สมชาย ใจดี
             ↳ p1 0-10 "สมชาย ใจดี"
Seniority  senior
             ↳ p1 11-72 "วิศวกรซอฟต์แวร์อาวุโส | somchai.j@example.com | กรุงเทพมหานคร"
...
verified 10/10  hallucination_rate 0.00%  attempts 1  cost $0.000000
match kinds: exact=10
```

---

## Architecture

```
Next.js (App Router, TS, Tailwind)
   │  REST
   ▼
FastAPI ──► PostgreSQL                      ← SQLite works for local dev
   │        Redis          (job queue)
   │        MinIO / S3     (or the local filesystem)
   │
   └─ enqueue ─► ARQ worker            ← or QUEUE_BACKEND=inline, no Redis
                    ▼
        parse → extract → verify evidence      (one resume)
        judge requirements → verify evidence   (one screening)
                             │
                             └─► LLM provider (fake | gemini)

        rank · retrieve                        (pure functions, no model call)
```

Upload stores the file, queues the work and returns a `pending` resume. The client
follows `GET /resumes/{id}/events` until the status settles, and falls back to polling
`GET /resumes/{id}` when the stream ends without a verdict.

Ranking and retrieval deliberately spend nothing: both are pure functions over rows
that already exist, which is what lets a recruiter adjust a weight and watch the list
reorder without re-billing a single screening.

### Provider-agnostic by design

`LLM_PROVIDER` selects the backend. The default, `fake`, is a rule-based extractor
that reads the actual document, so **the entire test suite and a full local demo
run with no API key and no spend** — and CI never depends on a third-party API
being up. `gemini` uses Gemini's free tier for real extraction. See
[docs/llm-providers.md](docs/llm-providers.md) for costs and how to add another.

The fake is not a stub returning canned data: it extracts real text and quotes it,
so evidence verification behaves exactly as it does in production. It also has a
`hallucinating` mode that cites text which is not in the document, which is how the
dropped-claims path is tested and demoed.

---

## What is measured

Recorded per document, with no labelling required:

| Metric | Source |
|---|---|
| Hallucination rate | Share of quotes the resolver could not locate |
| Verified vs dropped claim counts | Same |
| Match-kind breakdown | Which of the three matching tiers each quote needed |
| Model calls per document | Retries spent re-asking about rejected quotes |
| Latency per document | `llm_call_logs`, one row per call, with prompt version |
| Cost per document | Same — but **every figure is currently `$0.00`**, because the only live provider maps every model to a free tier. The column is real and the rule is enforced (an unknown price renders `unknown`, never `$0.00`); there is simply nothing to charge yet |

All of them are on the `/metrics` dashboard, which is a query over rows the system
already wrote and spends no model call of its own.

Deliberately **not** claimed: ranking quality against a BM25 or embedding baseline.
That needs a labelled gold set, and a project that stakes its success on beating a
baseline it has not measured invites unbounded work.

**Reviewed and closed unbuilt on 2026-08-16**, rather than left open as an optional
milestone. Four things ruled it out, and they are worth stating because "we ran out of
time" would be a different and less honest claim:

- **A ranking score and a retrieval score are not comparable**, which `pipeline/retrieval.py`
  has said in its own docstring since M3. BM25 is a *retrieval* scorer; ranking answers
  what a candidate's citations prove. Comparing them is a category error.
- **The lexical retriever already is BM25's idea**, minus the tuning knobs — so the
  honest version of the question shrinks to whether tuned BM25 beats untuned BM25.
- **An embedding baseline is a paid call**, and this project only ships a paid provider
  together with a current price table and a recorded live verification run. That is an
  adapter, not an evaluation.
- **The corpus is nine synthetic resumes written to exercise the parser**, and real
  resumes may never enter this repository. Labelling one's own documents against one's
  own job postings produces a number nobody should trust — which is the one thing this
  project exists to refuse.

---

## Known limitations

Recorded honestly, with tests pinning current behaviour so fixes are visible:

- **A `.docx` citation always says page 1.** Word decides where pages break when it
  renders, so the file does not say — and inventing a page number would be a guess
  presented as a fact. Tables *are* read, in document order, because that is where a
  resume usually keeps its skills.
- **Column detection is conservative, so some two-column layouts still interleave.**
  M2 #6 reads a two-column page one column at a time, but only where it is confident:
  an unusually narrow gutter, or columns wildly unequal in size, fall back to
  pdfplumber's visual order, where a job title from the right column can land beside
  contact details from the left. That direction is deliberate — a page wrongly split
  reorders text that was fine. Quotes stay truthful either way; adjacency is what
  misleads. Pinned by `tests/test_layout.py`, which tests each guard separately.
- **OCR text is faithful to what was read, not to what was printed.** A scanned page
  is recovered with Tesseract (`OCR_ENGINE=tesseract`), and the recognized text
  becomes the document every quote is checked against — so the guardrail is
  unchanged and a fabricated quote is still dropped. What OCR cannot promise is that
  it read the page correctly, so a citation into an OCR'd page can faithfully quote a
  misrecognition. Those pages are named in `pages_from_ocr` and the UI says so. With
  `OCR_ENGINE=none` (the default) a scan is still reported rather than read, and
  genuinely blank documents stay distinct from scans, since OCR cannot rescue them.
- **Ambiguous citations are flagged, not resolved.** A quote such as `Python` that
  appears in both a bullet and a skills list is reported as ambiguous rather than
  guessed at.
- **A password change signs out every device, and one thing about it is still worth
  knowing.** Each token carries the generation it was minted under (`epoch`), the account
  row carries the current one, and a mismatch is refused — so bumping one integer ends
  every session outstanding for that account without anything having to have recorded
  them. What it does *not* do is end them on any schedule but the next request: a token
  is refused when it is next presented, which for a client sitting idle means the session
  looks alive until it tries something. Pinned by
  `tests/test_api.py::TestChangePassword::test_a_session_on_another_device_is_signed_out_by_a_password_change`,
  which replaced the test that used to pin the opposite as a known limitation.
- **There is no "sign out everywhere" route**, though the epoch above makes one cheap.
  `/auth/logout` deliberately ends only the session it is given.
- ~~**Anyone may register as a recruiter.**~~ **Closed 2026-08-22.** It was recorded
  here as a gap this project could not answer: verifying that somebody really
  represents the company they claim to is an identity problem, and a check that proves
  nothing is worse than an honest hole. What dissolved it was not a solution to that
  problem but a decision about what this site *is* — one employer, HireLens itself
  (`docs/PLAN.md`, the careers-site section). There is no company left to verify anyone
  against, and a stranger claiming `recruiter` was never an unverified employer; they
  were a stranger inside this company's own hiring side. `SelfServiceRole` now has one
  member. `recruiter` and `admin` are both granted out of band, for the reason that
  always applied to `admin` alone: an account that can grant itself a role is not a
  role system. Pinned by `tests/test_rbac.py`, where the test that asserted the
  opposite is replaced rather than deleted — it would have gone on passing against the
  promoted fixture and proved nothing.
- **The web client's session is an httpOnly cookie**, so no token is reachable from
  script. What is left in `localStorage` is an identity marker — id, email, role —
  which React renders from and which is how one tab learns another signed out, since
  a cookie fires no `storage` event. Reading it gains nobody any ability to act.
  Two things follow that are worth knowing rather than discovering. **The browser and
  the API must be same-site**: cookies ignore ports, so `localhost:3000` reaching
  `localhost:8000` is fine, but `127.0.0.1:3000` is a different site and the cookie
  is withheld — the client names that cause rather than looking broken. And a
  cross-domain deploy needs `COOKIE_SAMESITE=none`, which throws away the CSRF
  protection `lax` provides; the `Origin` check on cookie-authenticated writes is
  what stands in for it.

## Test data

All resumes and job descriptions in this repository are **synthetic**. No real
person's resume is included. The PDF fixtures are generated by
[`api/tests/fixtures/generate.py`](api/tests/fixtures/generate.py) and committed, so
tests do not depend on a Thai-capable system font being installed.

## Tests

```bash
cd api && pytest -q            # 439 tests, no database, no API key, no Tesseract
cd web && npm run typecheck && npm test
```

A further 38 are skipped unless you opt in to the real thing — Postgres, Tesseract,
MinIO, or a billed provider. `CLAUDE.md` lists the environment variable each needs.

CI runs lint, format, types, tests, a migration up/down round-trip, and the web
build.
