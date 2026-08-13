# Handoff

Written 2026-07-30 at the end of M1, rewritten 2026-08-07 after the Postgres
cutover, again 2026-08-08 when M2 completed, and updated the same day when M3's
scope was agreed and its first slice landed. Updated 2026-08-12 when slice 5 put a
face on the matching engine, again when slice 6 closed **M3**, and again the same
day when all five slices of **M4** landed, and again on 2026-08-13 when slice 5 was
finally watched in a browser, turned out not to work, and had all seven of its defects
fixed. Read this first when picking
the project back up — then
`CLAUDE.md` for the rules and commands, and `docs/PLAN.md` for per-item milestone
status. Short dated session notes and owner advice live in `docs/NOTES.md`.

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

**M3 — the matching engine — is complete** (2026-08-12). Its scope was reviewed with
the owner on 2026-08-08 rather than reconstructed, and all six slices shipped against
the agreed shape: a job posting and its requirements are first-class rows with CRUD
behind them, a resume is judged against those requirements with every match cited, a
screening is a row of its own produced on the background worker under the shared retry
policy, screenings are ordered into a ranking, there is a UI a person can drive without
`curl`, and retrieval says which resumes are worth paying to judge.

**Three of the six slices cost no model call and no migration at all** — ranking,
the UI, and retrieval. That is the clearest sign the early slices stored the right
things: `GET /jobs/{id}/ranking` already returned verdicts *with* their citations, so
the UI needed no new endpoint, and retrieval scores text the database already held.
Ranking being a pure function over rows that already exist is worth preserving
specifically: it is what lets a recruiter drag a weight and watch the list reorder
without re-billing a single screening.

The idea that made the guardrail generalize, now shipped rather than planned:
**the model is never asked for a verdict.** It is asked only for quotes showing a
requirement is met, and the application derives `met` (a quote resolved) or
`not_evidenced` (none did) from what `EvidenceResolver` could locate — so judging
inherits the guardrail, the `dropped` list and the hallucination rate without any of
them being re-implemented. §5 says why `not_met` is deliberately not available.

**Retrieval is deliberately outside that guarantee, and cannot weaken it.** It orders
a list and produces no claim about anyone; delete the module and every verdict in the
system is unchanged. That is what makes it safe for it to be approximate.

**M4 — backend depth — is complete** (2026-08-12). Its scope was reviewed with the
owner the same day, the way M3's was, and all five slices shipped against the agreed
shape: a row whose worker died is reclaimed rather than stranded, an account has a
role, a candidate applies and their application moves through states somebody can
account for, a person can take a copy of what is held about them or have it erased,
and there is a UI for the journey.

**The idea that carried the guardrail into it:** §9 of the previous handoff asked that
anything making a *claim about a person* get the same treatment as a verdict. A
shortlist is such a claim. So **an application's state is never asserted — it is a
projection of an append-only log of transitions**, and replaying the log has to
reproduce it. Two rules fall out rather than being bolted on: you cannot shortlist
somebody who has not been screened (and the event records the screening it rests on),
and you cannot reject them without a reason. That is the same move as never asking the
model for offsets, and never asking it for a verdict, applied a third time.

**Two of the five slices needed no migration**, and the UI needed no API change at
all — `ApplicationOut` already carried what a list view renders, exactly as
`GET /jobs/{id}/ranking` did for M3's slice 5. Twice running, the slice that makes a
milestone visible has been cheap because the slices before it stored the right things.

**One M4 check never ran: nobody has watched the journey in a browser.** The Chrome
extension was not connected. Everything else is verified below, and that is not the
same thing — it is the first item in §9.

### Verified by running it, not only by tests

| Check | Result |
|---|---|
| `pytest -q` | **534** passed, 38 skipped, **no xfail** — 439 at the close of M3, plus 13 for the visibility timeout, 17 for RBAC, 39 for applications and 21 for PDPA, and 5 more from the 2026-08-13 walkthrough's fixes. The 38 skips are 4 Postgres + 12 Tesseract + 9 MinIO + 12 live-LLM, all opt-in. The two-column xfail started passing on 2026-08-08, which was its job (§7) |
| `npm test` | **62** in `web/` (28 at the close of M3, 43 at the close of M4): 16 for `lib/applications.ts`, 23 for `lib/api.ts` — including the table over every JSON write that would have caught the missing `Content-Type` — and 7 for `lib/requirements.ts`. Still **no DOM and no React testing library**, which is why one 2026-08-13 fix has no unit test and says so |
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
| The `EvidenceRecorder` extraction is inert | Extraction *and* judging output over four fixtures, before and after: byte-identical, captured by stashing `extract.py`/`judge.py` back to HEAD. The three judging mutations still fail 1/3/4 cases (2026-08-08) |
| **`page_spans` written by the real worker, in the containers** | After rebuilding `api` and `worker`: `resume_multipage.pdf` → 3 spans for 3 pages; `resume_th.pdf` → 10/10 verified, 0 dropped against live Gemini, and the last span's `char_end` (382) equals `length(document_text)` exactly, so the spans cover the text with no drift. Read out of `psql`, not the API (2026-08-08) |
| Migration `0006` on Postgres | `upgrade head` → `downgrade -1` → `upgrade head`; `alembic check` finds no drift (2026-08-08) |
| **Screening, end to end in the containers** | `/openapi.json` lists all three screening routes first — the proof the container serves the code just written. Then, against Postgres + Redis + the ARQ worker + real Gemini: upload → `extracted`, create a job with five requirements, `POST` answered **202**, the **worker** took it (`arq` log, job id `screening:…:0`), `completed` in 4.1 s. **3/5 met, 0 dropped**, every citation slicing back out of the returned `document_text`. The Thai requirement `งาน Backend ที่เกี่ยวกับระบบชำระเงิน` matched the resume's own `ดูแลระบบกระทบยอดการชำระเงินด้วย Python และ PostgreSQL`; `Kubernetes` and `ภาษาญี่ปุ่น` came back `not_evidenced` with no evidence attached (2026-08-08) |
| The staleness rule, watched rather than inferred | Asking again → **200**, `is_stale=false`, nothing queued. Changing a **weight** → still 200 and still not stale. Changing a **label** → `is_stale=true`, then **202** and a second worker dispatch under job id `screening:…:1`, after which `attempts=2` and the result is current again (2026-08-08) |
| Judging calls are billed to the screening | In `psql`: 21 `extract-v1` rows all carrying `resume_id` and none carrying `screening_id`; 2 `judge-v1` rows all carrying `screening_id` and none carrying `resume_id`. The two prompt families stay separable in the cost table (2026-08-08) |
| **Ranking, end to end in the containers** | `api` and `worker` rebuilt first, and `/openapi.json` lists `/jobs/{job_id}/ranking` plus all four ranking schemas. Then a job of 5 requirements (2 must-have, one Thai label round-tripping at 10 chars) over three resumes: `resume_en` and `resume_th` both 3/5 with the gate passed, `resume_multipage` 0/5 gated out and ranked last. The two that tie at 0.6000 are separated by the screening-id tie-break — the total order doing its job on real data (2026-08-08, on `fake` — see the note below) |
| **A weight change is free, watched in `psql`** | Patching one requirement's weight 1.0 → 20.0 moved every score (0.6000 → 0.9167) while all three screenings stayed `is_stale=false` with `attempts=1` — and Postgres shows **exactly one `judge-v1` row per screening** after two ranking requests and the patch. Then changing that requirement's *label* moved all three into `excluded` with `reason=stale` and left `ranked` empty. A second account gets **404** (2026-08-08) |
| The live run's provider | The judging behind that ranking ran on `fake`: the Gemini free tier's **daily** cap (20 requests for `gemini-3.6-flash`) was exhausted partway through, after `resume_en.pdf` had already completed against real Gemini at 3/5 met, 0 dropped. Ranking makes **no model call at all**, so the provider is not part of what this slice needed to prove — but nobody has yet watched a ranking built entirely from Gemini judgments (2026-08-08). **Closed 2026-08-12**: all six `judge-v1` rows are `gemini`/`gemini-3.6-flash`, read out of `psql` |
| **A ranking built entirely from Gemini judgments** | 3 resumes uploaded and `extracted` (12/12, 10/10, 7/7 claims verified, 0 dropped), a job of 5 requirements, 3 screenings each answered **202** and completed on the ARQ worker. `resume_th` and `resume_en` 4/5 met, `resume_two_column` 1/5. Every `judge-v1` row `provider=gemini` — the gap the previous entry recorded (2026-08-12) |
| **The whole M3 journey in a browser** | At :3000 against the containers and live Gemini: `/jobs` lists and authors, `/jobs/[id]` renders the requirement editor with a Thai label intact, the ranking table, and — on clicking a row — verdicts beside the document. The Thai requirement `งาน Backend ที่เกี่ยวกับระบบชำระเงิน` shows `Met` citing the resume's own `ดูแลระบบกระทบยอดการชำระเงินด้วย Python และ PostgreSQL`, and clicking that citation highlights exactly that line among 4 cited spans. `Kubernetes` reads "No citable evidence" with "That is not the same as the candidate lacking it" — the `not_met` refusal reaching the screen (2026-08-12) |
| **The must-have gate, visible** | With `Kubernetes` weighted 20, `resume_two_column` scores **83.3% — the highest on the page — and still ranks #3**, marked `0/2 — gate not passed`, below two candidates scoring 16.7%. A gate rather than a heavy weight, watched rather than inferred from a test (2026-08-12) |
| **Free vs billed, watched in the UI and in `psql`** | Editing a **weight** shows "Free — reorders the ranking without re-judging anyone" *before* saving; scores moved 16.7%/83.3% → 80.0%/20.0% instantly with every screening still `completed`. Editing a **label** warns that screenings go stale, then all three move into an amber "Not in the ranking (3)" section whose button reads "Screen again — **1 model call**". **Restoring the label brought all three straight back** — the fingerprint is content-based, not a timestamp. After the entire session `psql` shows **exactly one `judge-v1` row per screening, `attempts=1`** (2026-08-12) |
| **Two columns, rendered** | `resume_two_column.pdf` in `DocumentPane`: `CONTACT → nadia.w@example.com → Chiang Mai` and `SKILLS → Go, Kubernetes → Terraform, gRPC` read through **before** `EXPERIENCE`, rather than interleaving left and right. The M2 #6 fix seen by a human for the first time (2026-08-12) |
| **MinIO, rendered** | `STORAGE_BACKEND=minio docker compose up -d api worker` (an env var on the command line, so there is nothing to restore), then `resume_multipage.pdf` uploaded **through the browser**: `extracted`, 3 pages, the document pane rendering all three. `mc ls` shows the object; the same key is **absent** from `/data/uploads`; the worker logged `storage=minio`, and the stack was put back to `storage=local` afterwards (2026-08-12) |
| **Retrieval, live in the containers** | `api` rebuilt first, `/openapi.json` lists `/jobs/{job_id}/candidates` and `CandidateSuggestion`, and the startup log reads `retrieval=lexical`. Then, over three extracted resumes and a job whose only terms are a **Thai** requirement and `PostgreSQL`: `resume_th.pdf` ranks first at 1.0749 with the Thai label among its `matched` terms — the n-gram tokenizer finding a term buried in an unbroken run — `resume_en.pdf` second at 0.7313, and `resume_two_column.pdf` **scores 0.0 and is still listed** (2026-08-12) |
| The description really is not matched on | That same `resume_two_column.pdf` contains *every word* of the job's description (`Kubernetes Terraform gRPC`) and still scored **0.0**. Had the description steered retrieval it would have ranked first, so this is the decision being watched rather than asserted (2026-08-12) |
| Retrieval bills nothing | `psql` after the run: **0** `judge-v1` rows for that job, and the only calls against the account are the `extract-v1` ones its uploads needed. The ordering cost one query (2026-08-12) |
| **A worker killed mid-job, end to end** | `api` and `worker` rebuilt first, and the *container* asked what it holds (`cron_jobs` → `cron:reclaim`, `can_retry` a 2-arg predicate) — slice 1 adds no route, so `/openapi.json` proves nothing here. Then `docker compose kill worker` the instant the row read `processing`: `psql` shows `PROCESSING attempts=1 failed_attempts=0` and **no** `failure_reason` — the job never got to fail. `can_retry=false`, `POST /retry` → **409** (2026-08-12) |
| The `can_retry` boundary, measured not assumed | Ageing that row's `last_attempt_at` by hand against a 30 s timeout: **29 s → `can_retry=false`, 409; 31 s → `true`, 200.** Read from Postgres, where `last_attempt_at` is `timestamptz` — the dialect the SQLite naive-datetime test cannot cover (2026-08-12) |
| **The reaper, in the worker log** | `cron:reclaim` fires at startup and on the minute. On the stalled row: `stalled at processing, reclaiming` → `attempt 1 failed (WorkerVanished), retrying in 5s` → `queued as job resume:…:1` → `reclaimed 1 row(s) stalled beyond 30s`. The reclaim goes through `decide_retry`, watched rather than inferred (2026-08-12) |
| The budget guard, proven by an unplanned provider outage | Gemini answered **503 UNAVAILABLE** on the requeued job, so the row failed twice more at 5 s and 10 s and **dead-lettered after 3 attempts — of which the reclaim was attempt 1**. That is exactly the property a plain status reset would lose: it would have looped forever instead. Nobody scripted this; the provider obliged (2026-08-12) |
| The replay, and the citations after all of it | `POST /retry` on that dead letter → 200 → `extracted` on **attempt 4** once Gemini recovered: **10/10 verified, 0 dropped, 10/10 spans slicing back out of `document_text`, all tier-1 exact, no NUL** (2026-08-12) |
| **A screening reclaimed the same way** | Created with the worker stopped, so it queued without spending anything, then stranded at `processing` with a 120 s-old claim: `can_retry=true`. Starting the worker reclaimed it and it **completed 2/2 met** on attempt 2. `psql` afterwards: 1 `extract-v1` carrying `resume_id`, 1 `judge-v1` carrying `screening_id`, neither crossed — the M3 cost split survives the reaper (2026-08-12) |
| **Roles, live in the containers** | `api` and `worker` rebuilt first, then asked directly (`'role' in Candidate.__table__.c` → True). A recruiter and a candidate registered; `GET /auth/me` reports each. The candidate gets **403** on `POST /jobs` and on `PATCH` of the recruiter's job, **404** on `GET` of it, and **200** on `GET /jobs` — the two refusals staying apart on real data, and reads staying open so slice 3 can have candidates see a posting (2026-08-12) |
| Roles are stored as enum **names** | `psql` shows `RECRUITER` / `CANDIDATE`, not the lower-case values the API serializes — the §7 split, and what migration `0007` declares (2026-08-12) |
| Migration `0007` on Postgres | `downgrade -1` drops the column (`information_schema` says 0), `upgrade head` puts it back and re-runs the backfill; `alembic check` finds no drift, and the column lands **NOT NULL with no server default left behind** — the default exists only to fill existing rows (2026-08-12) |
| **The application journey, end to end in the containers** | `api` and `worker` rebuilt first, `/openapi.json` lists all five application routes. Then, against live Gemini: a recruiter posts a job whose second requirement is Thai, a candidate uploads `resume_th.pdf` and applies (**201**, then **200** on applying again). The recruiter reads that resume — **404 before the application, 200 after** — and is still refused `POST /resumes/{id}/retry` with **404**, because being shown a CV is not being handed the controls for it (2026-08-12) |
| **A shortlist that cannot be made without evidence** | `POST /transitions {shortlisted}` before any screening answers **409**: *"An application can only be shortlisted once it has been screened, so there is cited evidence behind the decision."* Screening it moves the application `applied → screening → screened` with nobody asking, and only then does the shortlist succeed (2026-08-12) |
| A rejection cannot be made silently | `{rejected}` with no reason answers **409** — *"Moving an application to rejected needs a reason."* The same instinct as `dropped` and `excluded`, at the level of a decision about a person (2026-08-12) |
| **The audit log, read from `psql`** | Four rows in `position` order: `→ APPLIED` by the seeker (role `CANDIDATE`), `APPLIED → SCREENING` and `SCREENING → SCREENED` by **(system)** with the screening id attached, `SCREENED → SHORTLISTED` by the hirer (role `RECRUITER`) with the same evidence. The system's moves are anonymous and the people's are not (2026-08-12) |
| The ranking names a resume the recruiter cannot list | `GET /jobs/{id}/ranking` returns `resume_filename=resume_th.pdf`, 2/2 met, gate passed — while `GET /resumes` for that same recruiter returns **0**. That gap is exactly what the client-side join used to fall into (2026-08-12) |
| Thai survived the whole thing | The job's second requirement reads back from Postgres at **36 characters / 90 bytes** — sent from a `.json` file rather than a shell literal, per §10 (2026-08-12) |
| **Consent, live against MinIO** | The wording served unauthenticated at `/resumes/consent`; upload with **no consent field → 422**, with `consent=false` → **422**, with `consent=true` → 201 and `extracted`. The refusal is schema validation, so nothing is stored either way (2026-08-12) |
| **Export carries the substance** | `GET /auth/me/export` for that account: 1 resume with its **382 characters of `document_text`**, the verified profile (`สมชาย ใจดี`), the consent version and timestamp, and the one `extract-v1` call it cost. A summary would have made the right to a copy decorative (2026-08-12) |
| **Erasure, watched in the bucket** | `DELETE /auth/me` reported 1 stored file removed; the token then answered **401**; `psql` shows 0 candidate rows and 0 resume rows; and `mc ls` shows **0 objects** under that account's prefix. Run on `STORAGE_BACKEND=minio` on purpose — a filesystem cannot show "the object outlived the row" the way a bucket can, and that orphan is the failure the blobs-first order exists to prevent (2026-08-12) |
| SQLite was ignoring every `ON DELETE` clause | Found by writing the cascade test and watching it fail for the wrong reason: SQLite does not enforce foreign keys unless asked, so `CASCADE` and `SET NULL` were inert there and live on Postgres — **and the whole suite runs on SQLite**. `PRAGMA foreign_keys=ON` now, in `db.build_engine` and in the test engine. Mutation-tested: turning it off fails 4 cases (2026-08-12) |
| **The application journey's data, panel by panel** | Every call each new screen makes, against the containers and live Gemini: `/applications` gets `role=candidate` and one application (`Backend Engineer · resume_th.pdf · applied`); `/jobs/{id}` gets one applicant. Shortlisting before a screening is **refused by the server with the same sentence the UI disables the button with**; after screening it succeeds. The timeline reads `#0 The candidate applied / #1 The system moved it to screening [cited evidence] / #2 The system moved it to screened / #3 The employer moved it to shortlisted` — matching `describeEvent` exactly (2026-08-12) |
| The bundle a browser would load | `npm run build` clean, `/applications` a 200 from the container, and the container's own `.next/static/chunks` carry the new strings. Note the honest limit: the pages return `null` until the client auth hook is ready, so **fetching the HTML proves nothing** — that probe came back empty and the instrument was wrong, not the code (2026-08-12) |
| ~~⚠️ **Nobody has watched slice 5 in a browser**~~ | **Closed 2026-08-13**, and it found **seven defects, four of them blocking** — the row below. The warning was right: every gate was green, every call each panel makes was verified, and the screens still did not work (2026-08-12) |
| **Slice 5, watched at last — and it did not work** | The Chrome extension connected for the first time on 2026-08-13. What rendered was correct; what a person could *do* was almost nothing. **A candidate could not see any posting** (`GET /jobs` filtered by owner → `200 []`), so applying was unreachable. **`Create job` would not submit** — the weight input's `min=0.1 step=0.5` made its own default of `1` invalid. **A recruiter could not screen an applicant** — the picker was built from `GET /resumes`, which returns only their own — so the disabled Shortlist could never unlock. And **every transition answered 422**, because `moveApplication` and `applyToJob` skipped the `json()` helper and sent no `Content-Type`. All four fixed and re-verified the same day (2026-08-13) |
| **The journey, browser-only, after the fixes** | Against the containers and live Gemini, with no `curl` anywhere: a recruiter authors a job leaving both weights at the **default**, a candidate uploads `resume_th.pdf` with consent (10/10 claims verified, 1 model call), sees `Backend Engineer` in *Apply to a job*, applies, and the recruiter screens that applicant from their own panel — 100.0%, 2/2 met including the Thai requirement — then shortlists. `psql` afterwards: `#0 → APPLIED` by `CANDIDATE` **with** `actor_id`, `#1`/`#2` by **(system)** with `actor_id` null and a screening attached, `#3 → SHORTLISTED` by `RECRUITER` with both. The Thai label reads back at **36 characters / 90 bytes**, typed through the browser (2026-08-13) |
| Consent, watched rather than inferred | The box is **unticked on load** (`useState(false)`) and the file picker is **disabled until it is ticked** — so an upload cannot assert an agreement nobody made. The earlier ticked state in this session was a stray click of mine, not a default (2026-08-13) |
| Erasure, through the API | Both throwaway accounts erased with `DELETE /auth/me`: `stored_files_removed: 1`, the token then 401, and `psql` reports 0 rows. The blobs-before-rows order exercised for real rather than only in tests (2026-08-13) |
| **The other three defects, fixed and watched** | The whole journey re-walked a second time on the rebuilt container against live Gemini, browser-only. A **recruiter account created from the browser** — impossible before, since `AuthPanel` sent no role — with the "nothing here verifies that you represent an employer" note showing on the recruiter choice. Then, with the applicants panel sampled every 400 ms and **nothing reloaded**: `t=0.0s APPLIED (1)` with Shortlist disabled reading *"Screen this candidate first…"*, `t=0.4s BEING SCREENED (1)` reading *"A screening is running."*, `t=20.5s SCREENED (1)` with Shortlist **enabled**. After shortlisting, the disabled button reads **"Already shortlisted."** — the sentence that was wrong. Timeline: *The candidate applied / The system moved it to being screened / …to screened / The employer moved it to shortlisted*, the last three carrying `cited evidence`. Ranking names `resume_th.pdf`, no console errors, both accounts erased (2026-08-13) |
| The Thai requirement, and what it proves | `ภาษาไทย` typed as a `language` requirement came back **not met** against a resume written entirely in Thai — because the document never *states* a language proficiency, so no quote can be located for it. That is `not_evidenced` doing its job, not a miss: the alternative is inferring a claim about a person from the fact that their CV is in Thai (2026-08-13) |
| Migration `0009` on both dialects | Postgres round-trip with `alembic check` clean, `consented_at` landing as `timestamp with time zone` and both columns nullable; SQLite `upgrade head` → `downgrade base` (2026-08-12) |
| Migration `0008` on both dialects | `upgrade head` → `downgrade -1` → `upgrade head` on Postgres with `alembic check` clean, and `upgrade head` → `downgrade base` on SQLite, which is where CI runs it (2026-08-12) |
| The backfill derives, and that has a cost | Three accounts through the round-trip: the one owning a posting came back `RECRUITER`, and **a recruiter owning no posting came back `CANDIDATE`**. No downgrade could preserve that — dropping the column discards the only record of it — so the migration says to re-run it only if you are prepared to re-grant roles (2026-08-12) |

### Repository state

`main` is on GitHub at <https://github.com/67160366/hirelens>, and **all of M3, all of
M4 and all seven of the 2026-08-13 walkthrough fixes are pushed and green on CI** (run
`31678374829`, 2026-08-13 — both the `api` and `web` jobs, including
`Verify migrations apply and reverse`, the step that caught migration `0006`). A local
run reports **534 passed, 38 skipped**, and the runner — no Tesseract, no database, no
MinIO, no API key — reports the same, which is the opt-in test design doing its job.
Plus **62** vitest cases in `web/`. Recent runs carry **no annotations at all**, which
is new: earlier green runs still emitted Node deprecations from inside
`actions/setup-node`. Read them anyway — §1's `setup-uv` story is why, and both jobs of
`31678374829` were re-checked for annotations rather than assumed clean from the tick.

**Check `git rev-list --count origin/main..main` rather than trusting the paragraph
above** — it was wrong for two commits before this one was corrected. A batch of
verified-but-unpushed commits is the easiest way for local and CI to drift apart —
slice 1 sat in the working tree, uncommitted, for a whole session — and CI is the
only thing that tests a clean machine with no `.env`, no Docker and no API key.

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

Roughly 30 minutes to get oriented on the pipeline, 15 for the job layer, and 15
more for M4's application layer (12–14).

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
| 12 | **`api/app/applications.py`** | M4's heart, and short: which moves an application may make and who may make them. Pure, like `decide_retry`. The two rules worth reading twice — a shortlist needs the screening it rests on, a rejection needs a reason — are enforced here and nowhere else |
| 13 | `api/app/services/application_service.py` | The only writer of `Application.state`, and it never writes it without the event that caused it. That pairing is the design |
| 14 | `api/app/services/privacy_service.py` | Export and erasure. Read the deletion order and why it is that way round |
| 15 | `docs/PLAN.md` | Milestones M2–M6 and the reasoning behind the scope calls |

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
    ranking.py         M3: judge's downstream twin — orders screenings with no model
                       call at all. Weights come from the job, not the stored result
    retrieval.py       M3: the pre-filter — which resumes are worth *paying* to judge.
                       A hint, never a gate: it returns every document, ordered, and
                       produces no claim, so it cannot weaken the guardrail. Thai is
                       tokenized by character n-gram because it has no word spaces
    verification.py    the resolve-and-tally loop both of the above run. Its own
                       module because it needs `evidence` *and* `schemas.profile`,
                       and `schemas.profile` imports `evidence` — a cycle otherwise
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
    ranking.py         M3: a ranked entry carries its citations, and an excluded one
                       carries why — nothing is dropped silently
  models/core.py       candidates (with M4's `role`), resumes, extracted_profiles,
                       llm_call_logs
  models/matching.py   M3: jobs, the requirements they are screened by, and a
                       screening — one resume judged against one job
  models/application.py  M4: an application, and the append-only log of every
                       move it made. `state` is a projection of that log
  applications.py    ★ M4: which moves are allowed and who may make them. Pure,
                       like `decide_retry` — and the one place the rule lives that
                       a shortlist needs evidence and a rejection needs a reason
  services/application_service.py  M4: the only writer of `Application.state`,
                       and it never writes it without the event that caused it
  services/screening_service.py  M3: request one (idempotent on the fingerprint),
                       and do the work from a worker
  storage.py           LocalStorage / MinioStorage behind one interface
  services/resume_service.py   upload path: store, insert, queue; and process_resume
  jobs.py            ★ run_resume_job, run_screening_job, and `decide_retry` — the
                       retry policy, pure and shared by both
  queue.py             JobQueue seam: inline (no server) / arq (Redis)
  worker.py            `arq app.worker.WorkerSettings` — adapter only
  logging_config.py    shared by API and worker so the worker need not import the app
  api/deps.py          M4: `require_role` beside `CandidateDep`. 403 for a route a
                       role may not reach; ownership still answers 404
  api/routes/          auth.py, resumes.py — upload, profile, retry, progress stream
                       jobs.py — postings and requirements; requirement routes are
                       nested so ownership is settled in one place
                       screenings.py — creation nested under /jobs, reads flat under
                       /screenings; 202 when work was queued, 200 when it was not.
                       Also GET /jobs/{id}/ranking and GET /jobs/{id}/candidates,
                       neither of which spends anything
  cli.py               `python -m app.cli <pdf>` — fastest way to see output
web/
  app/page.tsx         auth + upload + live progress + result + retry
  app/jobs/page.tsx    M3: job list, and authoring a job with its requirements in one call
  app/jobs/[id]/page.tsx  M3: the slice-5 screen — requirement editor, screening,
                       ranking, and one candidate's verdicts beside the document
  lib/api.ts           typed client; `waitForProfile` streams, then falls back to polling.
                       `createScreening` returns `queued` because 202-vs-200 is a
                       design decision the UI has to be able to report
  lib/auth.ts          M3: the session, shared by every route — token storage and the
                       refresh-once-on-401 wrapper, lifted out of `page.tsx`
  lib/screening.ts     M3: the pure judgment logic the ranking screen runs on. Its own
                       module so `npm test` needs no DOM, the same instinct as the
                       Python suite needing no server
  components/Evidence.tsx, ProfileView.tsx, DocumentPane.tsx (citation highlighting)
  components/RankingTable.tsx, JudgmentView.tsx, RequirementEditor.tsx,
                       RequirementFields.tsx, AuthPanel.tsx
  app/applications/page.tsx  M4: the candidate's half — apply, follow, withdraw
  lib/applications.ts  M4: which moves to *offer*, and how the log reads. It
                       deliberately does not decide what is allowed — the server
                       does, and a second copy of those rules is the one that
                       drifts unnoticed
  components/ApplicationTimeline.tsx, ApplicationActions.tsx
```

`DocumentPane` takes `references: EvidenceRef[]`, **not** a profile. That change is
what lets a screening's citations highlight through the component M1 wrote for
extraction claims — the offsets index into the same `document_text` either way.

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
- **The retry policy answers in intents, not statuses** (M3 slice 3). `decide_retry`
  is pure — an error plus a failure count in, `PERMANENT`/`RETRY`/`EXHAUSTED` out —
  and each job maps that onto its own vocabulary. `Resume` and `Screening` keep
  separate status enums because a screening is never `parsed` or `extracted`; sharing
  one enum would have leaked each table's states into the other, and sharing the
  *decision* is what actually stops the two policies drifting apart.
- **A completed screening is re-runnable; an extracted resume is not** (M3 slice 3).
  Redoing an extraction bills a second call for a profile we already have, and the
  document cannot change. A screening's requirements *can* change, so `run_screening_job`
  does not refuse a completed row — the waste is prevented one layer up, where
  `request_screening` queues only when `requirements_fingerprint` moved. That is why
  `POST /jobs/{id}/screenings` answers **202** or **200** rather than always the same
  thing.
- **The fingerprint covers what the judge saw, and nothing else** (M3 slice 3). Kind,
  label, detail and their *order* — the model refers to requirements by position, so a
  reorder is a different question. `must_have` and `weight` are excluded because they
  never reach the prompt: including them would invalidate correct screenings and spend
  a model call reproducing an identical answer every time someone adjusted a weight.
  `prompt_version` is stored beside the hash rather than folded into it so the two
  reasons a result can go stale stay distinguishable.
- **A judging call is billed to the screening, not the resume** (M3 slice 3).
  `LLMCallLog` has both `resume_id` and `screening_id`, and exactly one is set. Hanging
  a judging call off the resume would corrupt "what did extracting this document cost";
  leaving it unrecorded would make every cost figure quietly incomplete, which is the
  same class of failure as a stale price table.
- **Ranking reads `must_have` and `weight` from the job, never from the stored
  judgment** (M3 slice 4). `RequirementJudgment` persists both, frozen at judging
  time — and `requirements_fingerprint` excludes both on purpose, so editing a weight
  leaves the screening *current* while the stored JSON keeps the old number forever.
  Reading them back out of `result` is the obvious implementation, passes every test
  that does not specifically look for it, and silently makes weight edits do nothing.
  The join is **by position, not by id**: the fingerprint excludes ids too, so a
  current screening can carry ids the job no longer has, while `(kind, label, detail)`
  and their order are exactly what it does cover — and `verify()` emits one judgment
  per requirement in requirement order. A length mismatch is excluded as `malformed`
  rather than joined against the wrong requirement. Mutation-tested: reading weights
  from the stored result fails 5 cases of `test_ranking.py`.
- **A stale screening is excluded from a ranking and reported, not re-run**
  (M3 slice 4). Ranking a stale row beside fresh ones silently mixes answers to two
  different questions; auto-re-running spends a model call nobody asked for and would
  undo the whole point of keeping `must_have`/`weight` out of the fingerprint.
  `POST /jobs/{id}/screenings` stays the one place a caller chooses to pay for a fresh
  answer, and `excluded` carries the reason — the same instinct as `dropped`.
- **Must-haves count toward the score as well as gating it** (M3 slice 4). Inside the
  tier that passed the gate this is a constant and reorders nothing; inside the tier
  that failed it is what separates "missing one gate" from "missing all of them", and
  it keeps the denominator non-zero for a job made entirely of must-haves.
- **Retrieval is a hint, never a gate** (M3 slice 6). `Retriever.retrieve` scores every
  document it is given and returns all of them ordered; it never drops the tail. A
  retriever that filtered would remove a person from consideration with no way to see
  it happened — the same failure as a UI that hides `excluded` screenings, and worse,
  because it happens before anyone has looked. Choosing a cut-off is the caller's
  decision, made in the open. Mutation-tested: filtering zero scorers fails 9 cases.
- **Thai is tokenized by character n-gram, Latin by word** (M3 slice 6). Not a
  preference — a measurement. `resume_th.pdf` contains the unbroken 31-character run
  `ดูแลระบบกระทบยอดการชำระเงินด้วย`, and the real terms `ชำระเงิน` and `วิศวกรรม` sit
  inside it, where a whitespace tokenizer finds **neither**. The same probe showed how
  a test could hide it: `ทักษะ` happens to be followed by a colon, so it *is* a
  standalone token and a naive implementation looks correct on it. That is the
  two-column fixture with no header in a new costume, and it is why the Thai test cases
  use terms buried mid-run. 3 is the usual n-gram length for Thai: 2 collides across
  unrelated words, 4 starts missing short ones.
- **Retrieval matches requirement labels, never `job.description`** (M3 slice 6). The
  description is stored for context and audit and is explicitly not what anyone is
  judged against; letting it steer retrieval would reintroduce free-text scoring
  through the back door, on the one input nobody decomposed on purpose. Watched live
  rather than asserted: a resume containing every word of a job's description still
  scored 0.0.
- **`RETRIEVAL_BACKEND=pgvector` raises on purpose**, exactly as `LLM_PROVIDER=anthropic`
  does. Embeddings are a paid call, so the adapter lands only together with a price
  table and a live verification run in `docs/llm-providers.md` — a stale price silently
  corrupts every cost figure, and a backend nobody has run is worse than an honest error.
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
- **A role gates a route; ownership gates a row — 403 and 404, never merged**
  (M4 slice 2). A role check is about the *route*, which is listed in `/docs` and
  which the caller has plainly found, so naming the role it needs leaks nothing:
  **403**. An ownership check is about a specific *id*, and a 403 there would confirm
  the id exists — the account-enumeration answer `_owned_job` and `_owned_resume`
  were written to avoid: **404**. Collapsing the two is a one-line change with no
  visible symptom, which is why `test_rbac.py` asserts the codes rather than just
  that a request was refused. Mutation-tested: answering 403 on ownership fails 7
  cases. The role check runs as a dependency, *before* any row is read, so a
  candidate hitting a real id and an invented one get byte-identical responses.
- **`require_role` grants `ADMIN` implicitly** (M4 slice 2). A role system where
  every route has to remember to list the superuser grows a hole the first time
  someone forgets. Mutation-tested: removing it fails 1 case.
- **An application's state is a projection of an append-only event log** (M4 slice 3).
  `application_events` is the record; `Application.state` is written only in the same
  transaction as the event that caused it, and replaying the log has to reproduce it.
  This is §9's request with a body — a state transition is a claim about a person, so
  it is derived from something checkable or not asserted. Two rules fall out rather
  than being bolted on: **a shortlist is reachable only from `screened` and records
  the screening id it rests on**, and **a rejection requires a reason**. Both are
  enforced in `app/applications.py`, which is pure. Mutation-tested six ways.
- **An illegal transition is refused with its reason (409), never ignored** (M4 slice
  3). A state machine that quietly drops a move it dislikes produces a system where
  nobody can tell a decision from a bug. 409 rather than 400 or 404: the request is
  well formed and the caller is entitled to both the route and the row — the answer
  is about the move.
- **The event log is ordered by a stored `position`, not by `created_at`** (M4 slice
  3). Timestamps looked sufficient and were not: SQLite's `CURRENT_TIMESTAMP` has
  one-second granularity, so a journey taking milliseconds writes every event with an
  identical time and the tiebreak falls through to a *random UUID*. The log came back
  shuffled in a test. `uq_application_events_application_position` makes the sequence
  a fact rather than a probability.
- **`Actor` carries the account id rather than deriving it** (M4 slice 3). The first
  version worked it out from the mover — the applicant's id is on the application, and
  the job owner's is not — so **every recruiter decision was logged as though the
  system had made it**. The test that should have caught it asserted `actor_role`,
  which was correct, and not `actor_id`. Found by reading a live audit log, not by the
  suite. `actor_id` is null for the system and only for the system.
- **A recruiter may read a resume applied to a job they own, but not act on it**
  (M4 slice 3). `_owned_resume` widens for reads and keeps `must_own` for
  `POST /retry`: replaying an extraction spends a model call billed to the resume and
  belongs to whoever uploaded it. Being shown a CV is not being handed the controls
  for it. Screening is scoped to the *one* posting applied to — applying somewhere is
  not blanket consent to be judged against everything the same recruiter has open.
- **Erasure deletes the stored files before the rows, and abandons everything if
  one will not go** (M4 slice 4). The other order is the one that quietly fails
  PDPA: rows gone, object still in the bucket, and nothing left pointing at it for
  anyone to notice — undiscoverable and therefore unerasable. This way the worst
  case is a row whose file is missing, which the pipeline already treats as a
  permanent failure and reports. A `StorageError` answers **503** with nothing
  changed; an `ObjectNotFoundError` is not a failure at all, because already-gone is
  the outcome being asked for.
- **Export is a subject-access request, not a dump of everything you can see**
  (M4 slice 4). A recruiter may read the resumes of people who applied to their
  postings — slice 3 widened `_owned_resume` for exactly that — and those belong to
  the applicants, who export them from their own accounts. What comes back is what
  is *about* the caller, including `document_text` and the verified profile:
  withholding the substance would make the right to a copy decorative.
- **Consent has no default and is stored with its version** (M4 slice 4). A field
  defaulting to true is not consent, so `POST /resumes` has none and a missing one is
  a 422 from the schema — before a byte is stored or a call is billed. `consent_version`
  sits beside `consented_at` for the reason `prompt_version` sits beside
  `requirements_hash`: "they consented" and "they consented to *this wording*" are
  different claims, and only one survives a rewrite. `GET /resumes/consent` serves the
  text so a client shows it rather than inventing its own, and the web client sends
  what the box says rather than a hard-coded `true`.
- **SQLite is told to enforce foreign keys** (M4 slice 4, `db.enforce_foreign_keys`).
  It does not by default, so `ON DELETE CASCADE` and `ON DELETE SET NULL` were inert
  there and enforced on Postgres — and **the entire suite runs on SQLite**, so nothing
  could see the difference. Same class as SQLite storing the NUL that Postgres refused
  (§11). Found by writing the erasure test and watching it fail for the wrong reason.
- **The role is read from the row, never carried in the token** (M4 slice 2).
  Putting it in the JWT would mean a demotion did nothing until the access token
  expired — a window in which a permission you removed is still live. Every check
  reads `candidates.role`, so the next request is already correct, and `GET /auth/me`
  reports it so a client can render the right home page without probing a route to
  see whether it 403s.
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
| `processing` | A worker has claimed it. Held here past `JOB_VISIBILITY_TIMEOUT_SECONDS` means the worker died, and the reaper (below) moves it back. |
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
rows — see the status table), and since M4 slice 1 for a `processing` row held past
the visibility timeout; 409 for `pending`, `extracted` and a `processing` row a
worker is plausibly still holding. `ResumeOut.can_retry` tells a client the answer
without reimplementing the rule — it takes `Settings` now, because the answer is
time-dependent — and the web UI shows a "Try again" button from it.

### Reclaiming a row whose worker died (M4 slice 1)

Everything above handles a job that *fails*. A job whose process simply stops —
power loss, OOM, `docker kill` — never gets to fail: the claim is committed, and
then nothing. The row sits at `processing` where every road out was closed.
Redelivery skips it (`processing` is in `_NOT_OURS_TO_RUN`), `POST /retry` answered
409, and re-uploading the same bytes dedupes onto it.

`jobs.reclaim_stalled` is the sweep. `app/worker.py` registers it as an arq cron
job, once a minute and at startup, with arq's `unique=True` so replicas do not each
reclaim the same row.

Three things about it are deliberate:

- **It reuses `decide_retry` rather than resetting the status.** A reclaim counts
  against `failed_attempts`, so a document that kills its worker every time
  dead-letters after the budget instead of looping reap → requeue → die forever.
  That loop is the failure mode a reaper introduces, and inheriting the policy is
  what forecloses it. Mutation-tested: a plain status reset fails 3 cases.
- **Listing a candidate and reclaiming it are separate functions on purpose.**
  `_record_failure` commits, which drops whatever locks the candidate query took —
  so the list cannot be trusted, and `reclaim_resume` re-reads each row
  `with_for_update` and re-tests it. In the gap a `POST /retry` can move the row to
  `pending`, a worker can claim it afresh, or the original can finish; reclaiming
  then would spend the budget on a run that is alive. Mutation-tested three ways.
- **A `processing` row with no `last_attempt_at` counts as stalled.** The claim
  writes both in one commit, so that combination cannot be held by anything running.

And one trap the tests had to be reshaped to catch: two sweeps back to back prove
nothing, because the second one's *candidate query* already excludes a row the first
moved to `pending` — the guard under the lock never runs. That test passed against
a version with no guard at all. `test_a_listed_row_that_stopped_qualifying_is_left_alone`
drives `reclaim_resume` directly instead.

**The manual half.** `POST /resumes/{id}/retry` and `POST /screenings/{id}/retry`
now accept a row stalled past the timeout, and `can_retry` says so — which is what
actually closes "no way back through the API", and is the *only* half that exists
under `QUEUE_BACKEND=inline`, where there is no worker to run a cron.

### What `InlineQueue` does not do

It cannot defer work, and sleeping through a backoff would hold the upload request
open for the length of it. So it never retries: a transient failure leaves the
resume `pending` with the reason recorded, and re-uploading the file picks it up
again. It also runs no reaper, for the same reason — there is no process to schedule
one on. That is a property of running without a queue, not a bug — deployments that
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
- **Judging never sees `must_have` or `weight`, and that is the point.** They travel
  on `RequirementSpec` and come back on `RequirementJudgment` untouched, for ranking
  (slice 4) to read. Whether a requirement is evidenced is a question about the
  document; how much it matters is a question about the job. A judge that consulted
  the weight would be scoring, which is the thing this milestone refuses to become.
- **Lexical retrieval scores every document in memory, on every request.** No index,
  nothing to keep in sync, and it works on SQLite — which is why the suite still needs
  no server. It is linear in total document length per request, so it is the right
  trade at one recruiter's pile of resumes and the wrong one at thousands per job.
  That is what the `Retriever` seam is for, and `PgVectorRetriever` is where it goes.
- **Retrieval has no quality measurement, on purpose.** Nothing here says the order it
  produces is *good* — only that it is deterministic, explainable and free. Judging
  ranking quality against a BM25/embedding baseline needs a labelled gold set and is
  M6 with a one-week timebox (§scope discipline in §10). Do not quietly promote it.
- ~~**A resume stuck at `processing` is never reaped.**~~ **Closed 2026-08-12** by
  M4 slice 1: `jobs.reclaim_stalled` sweeps rows held past
  `JOB_VISIBILITY_TIMEOUT_SECONDS` (900), and `POST /retry` accepts one by hand.
  What is still true is the trade underneath it — the claim writes
  `last_attempt_at` once and never heartbeats, so the timeout has to cover a whole
  job rather than a step of one, and a worker that is merely *slow* past 15 minutes
  gets reaped and its work duplicated. Harmless (the loser's `_claim` sees
  `extracted` and skips) but wasteful, and a heartbeat is what would let the number
  come down.
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
  resume stranded at `processing` by a dead worker stops holding a connection open.
  The client polls on from there and sees the same nothing — which stays the honest
  answer until the visibility timeout expires, at which point the reaper moves the
  row and `can_retry` turns true. The cap (300 s) is deliberately well under the
  timeout (900 s): a connection should not be held for the length of a sweep cycle.
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
| `test_judge.py` | Requirement-level judging: verdicts derived from what resolved, unknown/duplicate requirement numbers, the empty case, and the retry rule that differs from extraction's |
| `test_judge_live.py` | Judging against a real model — semantic matching, and that the guardrail holds on output nobody scripted. **Opt-in**, needs `TEST_LIVE_LLM=1`, and gated on that flag rather than on a key because `.env` already has one |
| `test_screening.py` | The fingerprint (what makes a result stale, and what must not), `decide_retry` on its own now that two job types share it, and the screening job: verdicts on a row, cost billed to the screening, failure and replay |
| `test_ranking.py` | The must-have gate, the weighted score, and the two things easiest to get wrong: that weights come from the job rather than the stored judgment, and that the order is total so a list never reshuffles. Pure — no session, like `test_judge.py` — plus the route |
| `test_llm.py` / `test_gemini.py` | The provider seam; Gemini's contract via mocks |
| `test_api.py` | Auth, upload gates, reading a profile back |
| `test_resume_service.py` | The duplicate-upload race, blob cleanup, PII-safe logging |
| `test_worker.py` | Upload enqueues; the job runs; the arq adapter |
| `test_retry.py` | Error classification, backoff, dead-lettering, replay |
| `test_events.py` | The progress stream: ownership, the frame sequence, the cap, keep-alives |
| `test_retrieval.py` | Tokenizing text with no word spaces, the ordering, and the property most easily lost: that retrieval is a hint and returns every document rather than filtering. The Thai cases use terms buried mid-run *on purpose* — a term with a space beside it passes against a tokenizer that is wrong for Thai |
| `test_postgres.py` | JSONB, Thai round-trip, JSON queries. **Opt-in**, needs `TEST_DATABASE_URL` |
| `test_config.py` | Settings validation, including the JWT-secret refusal |

And in `web/`, run by `npm test` (vitest, **no DOM and no React testing library** —
keeping that true is the same property as the Python suite needing no server):

| File | What it pins |
|---|---|
| `lib/api.test.ts` | The SSE frame parser across chunk boundaries, including a Thai character split in half — plus `createScreening` mapping **202 → queued** and **200 → already answered**, the one status code on this client that carries meaning |
| `lib/screening.test.ts` | That an unevidenced requirement contributes **no** highlight even if a payload carried spans, which fields make a screening stale (and that `weight`/`must_have` do not), and that the unevidenced wording never claims a candidate lacks anything |

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
| 3 | Screening as a row, on the background worker | **done** — `models/matching.py:Screening`, `services/screening_service.py`, `run_screening_job`, `api/routes/screenings.py`, migration `0006`, `tests/test_screening.py` |
| 4 | Ranking across candidates | **done** — `pipeline/ranking.py` + `schemas/ranking.py`, `GET /jobs/{id}/ranking`, no migration, `tests/test_ranking.py` |
| 5 | A thin web UI | **done** — `web/app/jobs/`, `lib/auth.ts`, `lib/screening.ts`, `components/{RankingTable,JudgmentView,RequirementEditor,RequirementFields,AuthPanel}.tsx`; **no API change, no migration**; `lib/screening.test.ts` |
| 6 | Retrieval — the pre-filter | **done** — `pipeline/retrieval.py`, `GET /jobs/{id}/candidates`, `RETRIEVAL_BACKEND`; no model call, no migration; `tests/test_retrieval.py` |

**M3 and M4 are both closed**, each after a scope review with the owner rather than
a reconstruction. **M5–M6 are still a draft**; review each the same way — it has now
paid for itself twice.

| # | Work | Status |
|---|---|---|
| 1 | The visibility timeout | **done** — `jobs.reclaim_stalled` + the arq cron in `worker.py`, `can_retry` as a predicate; **no migration**; `tests/test_retry.py` |
| 2 | RBAC: a role on the one actor | **done** — `Role` on `models/core.py`, `require_role` in `api/deps.py`, migration `0007` with a derived backfill, `tests/test_rbac.py` |
| 3 | The application and its state machine | **done** — `models/application.py`, `applications.py` (pure), `services/application_service.py`, `api/routes/applications.py`, migration `0008`; widened `_owned_resume` and moved the ranking's filename server-side; `tests/test_applications.py` |
| 4 | PDPA: consent, export, delete | **done** — `services/privacy_service.py`, `GET /auth/me/export`, `DELETE /auth/me`, `GET /resumes/consent`, migration `0009`, `PRAGMA foreign_keys=ON`; `tests/test_pdpa.py` |
| 5 | A thin UI for the journey | **done** — `web/app/applications/`, the applicants panel on `/jobs/[id]`, `lib/applications.ts`, `components/{ApplicationTimeline,ApplicationActions}.tsx`; **no API change and no migration**; `lib/applications.test.ts` |

**Four things to know before starting M5:**

1. ~~**Watch the application journey in a browser.**~~ **Done 2026-08-13, and it was
   the most productive twenty minutes of the milestone** — it found seven defects,
   four of them blocking, in code where every gate was green. §1 has them. The
   lesson to carry into M5 is the one this row keeps teaching in new costumes:
   **verifying every call a screen makes is not the same as using the screen.**
   Four of the seven were pure wiring — a missing header, a list built from the
   wrong endpoint, an input whose bounds rejected its own default — and none of
   them are the kind of thing a test of pure logic can see. Whatever M5 ships,
   somebody drives it in a browser *inside* the slice, not after it.
   **All seven are closed** as of the same day, one commit each. The last of them —
   the applicants panel not re-reading itself when a screening moves it — is the one
   worth remembering, because it is the first fix here that **ships without a unit
   test on purpose**. It lives in a component effect, and `web/` has vitest with no
   DOM by design (§5). The two tests that could have been written were both refused:
   an "applications agree with screenings" invariant needs the server's `_ALLOWED`
   table re-implemented on the client, which is exactly what `lib/applications.ts`
   exists to refuse, and asserting the refresh set restates the line above it. When
   the only available test would be decorative, say so in the commit and let the
   browser be the check.
2. **Keep the two kinds of refusal apart.** A wrong *role* for a route is **403** —
   the route is in `/docs` and saying so leaks nothing. Not *your* resource stays
   **404**, because a 403 there is an id-probing oracle. Mixing them is the easiest
   way to undo M3's whole ownership story.
   **One deliberate exception, added 2026-08-13: a job posting is public to read.**
   It is an advertisement, and `GET /jobs` now hands every posting's id to every
   candidate, so a 404 on the detail route was hiding something already public.
   Every *write* still answers 404, and so does everything the posting produced —
   a ranking, a screening, an applicant list all carry verdicts about named people
   and stay on `_owned_job`. That boundary is pinned by
   `test_a_public_posting_does_not_make_its_screenings_public`.
3. **Retrieval is still the only part of the system allowed to be approximate**,
   because it makes no claim about anyone. Everything M4 added that *does* make a
   claim went through the same treatment as a verdict, which is why an application's
   state is a projection of an append-only log rather than a column anyone may set.
   Hold that line in M5: an observability dashboard reports, and a recruiter UI must
   not start asserting what the API refuses to.
4. ~~**`next@16` is still owed.**~~ **Done 2026-08-13**, as its own commit rather than
   folded into a slice. `npm audit` is **0 high**. Four things to carry forward from
   it: `next build` now runs **Turbopack** and rewrites `tsconfig.json` and
   `next-env.d.ts` itself; `eslint-config-next` v16 exports flat config directly, so
   `FlatCompat` is gone and **ESLint stays on 9** because the config's own
   `eslint-plugin-react` has no ESLint 10 release; the new
   `react-hooks/set-state-in-effect` rule is suppressed at four sites with reasons
   rather than switched off, and `useAuth` still owes a `useSyncExternalStore` rewrite
   as its own commit; and `web/Dockerfile` needed **no change**, which was verified by
   assembling the standalone layout by hand rather than inferred from a green build —
   Turbopack has a known regression (vercel/next.js#88844) in exactly the directory
   that image copies.

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

- ~~**The browser has not seen the two-column or MinIO work.**~~ **Closed 2026-08-12**
  with slice 5, which is why `PLAN.md` put the walkthrough *inside* the slice rather
  than after it. A two-column resume reads CONTACT/SKILLS through before EXPERIENCE in
  `DocumentPane`, and a MinIO upload renders identically with the object in the bucket
  and absent from the uploads volume. It had slipped three sessions as a follow-up and
  took twenty minutes as a deliverable.
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
- **A migration must also run on SQLite, because CI runs it there.**
  `.github/workflows/ci.yml` has a `Verify migrations apply and reverse` step that
  does `alembic upgrade head` → `alembic downgrade base` against
  `sqlite+aiosqlite:///./var/ci.db`. Postgres passing is therefore only half the
  check, and the half this project is more likely to do. **SQLite cannot ALTER a
  constraint onto an existing table at all**, so `op.create_foreign_key` against a
  table that already exists fails there while passing on Postgres — and declaring the
  key inline on the column does *not* help, because alembic adds the column and then
  adds each of its constraints as a separate statement. Use
  `op.batch_alter_table`, which emits ordinary ALTERs on Postgres and rebuilds the
  table copy-and-move on SQLite. Migration `0006` was written the wrong way, verified
  on Postgres, and caught by CI. Run it locally before pushing:
  `DATABASE_URL=sqlite+aiosqlite:///./var/ci_check.db alembic upgrade head && alembic downgrade base`.
- **In a migration, name a check constraint with the bare name.** `ck` is the only
  convention in `models/base.py` that interpolates `%(constraint_name)s`, so
  `name="ck_<table>_<rule>"` gets wrapped a second time and `alembic check` reports
  drift against the model forever. `fk`, `pk` and `uq` names are safe spelled out —
  their conventions never reference the given name.
- **When a check says something surprising, suspect the instrument first.** Five
  tools have now each told a confident lie here: `git hash-object` reported
  CRLF-corrupted PDFs as intact because it normalizes while hashing, a
  `WHERE kind = 'language'` query returned nothing because SQLAlchemy stores enum
  *names*, PowerShell 5.1 rendered stored Thai as mojibake because it decodes a
  JSON body as Latin-1 when the server names no charset, and (2026-08-12) two more
  from one script. In each case the data was fine and the question was wrong. Go to
  the store that cannot lie — `psql`, and byte counts rather than eyeballs.
- **A `.ps1` without a BOM is read in the ANSI codepage, so Thai in a script literal
  is corrupted before it is ever sent** (2026-08-12). A live check "verified" a Thai
  requirement round-trip against text the script itself had already broken —
  `octet_length` in `psql` said 90 chars / 240 bytes where 36 / 90 belonged. This is
  worse than the mojibake above, which was only a display problem: here the wrong
  bytes really were stored. **Keep non-ASCII payloads in a `.json` file and send its
  bytes**, and check the length in the database rather than reading the console.
- **In PowerShell, assigning an `if` *expression* unrolls an array.**
  `$x = if (…) { $bytes } else { … }` sends the result through the pipeline, which
  re-collects a `byte[]` as `Object[]`; `Invoke-WebRequest` then posts that array's
  `ToString()` — the decimal bytes — and the server reports a JSON error at position 4
  because it parsed `123`, the `{`. Cast: `[byte[]]$x`. And do not name the temporary
  `$raw` inside a function with a `[switch]$Raw` parameter — PowerShell variable names
  are case-insensitive, so it silently overwrites the switch.
- **A function that both writes output and returns a value returns both.** PowerShell
  puts everything on the pipeline, so `$result = Show-Ranking "caption"` captures the
  printed lines too and nothing appears on screen. It cost one confusing run where the
  most important output of the check was simply missing.
- **Before believing a live run, prove you are testing what you built.** Three things
  have each caused a wrong conclusion here: a zombie server on the old port serving
  old code, a *second* ARQ worker left running from an earlier session quietly taking
  the job (2026-08-08 — the giveaway was the old wording in `failure_reason`), and a
  dev server on a port the API's CORS list did not allow. Check the route exists
  (`curl /openapi.json | grep <new-field>`) and that nothing else is polling the
  queue. **When a change adds no route, `/openapi.json` proves nothing** — ask the
  container what it holds instead (`docker compose exec worker python -c "…"`), the
  way the stale-model check did in 2026-08-08's cleanup pass.
- **An env var on a `docker compose up` command line does not survive the next `up`
  that omits it** (2026-08-12). `JOB_VISIBILITY_TIMEOUT_SECONDS=30 docker compose up -d
  api worker` set the timeout to 30 s; a later plain `docker compose up -d worker`
  recreated the container and re-resolved `${JOB_VISIBILITY_TIMEOUT_SECONDS:-900}` back
  to **900**, and the reaper then correctly did nothing for forty seconds while it
  looked broken. The 2026-08-08 note calls a command-line override convenient because
  "there is nothing to restore"; the other half of that is there is nothing to *keep*.
  Ask the container for the value before reading the result, not after it surprises you.
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
- ~~**The visibility timeout from §7.**~~ **Done 2026-08-12** as M4 slice 1 — pulled
  out of M5 because a row nobody can reach is a correctness problem, not an
  observability one. Bug 2's fix covered a commit that *fails*; this covers a worker
  that never gets as far as failing. `jobs.reclaim_stalled` sweeps it, `POST /retry`
  opens the same door by hand, and §6 has the three decisions inside it.
  **This closes the incident: nothing from §11 is outstanding.**
