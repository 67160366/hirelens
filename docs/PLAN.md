# Milestone plan

The working plan for HireLens, kept in the repository so any session — human or
agent — can see where the project is and what comes next. Update the status
column and checklists as work lands; refresh `docs/HANDOFF.md` when a milestone
completes.

M1–M2 reflect decisions already made and verified. **M3–M6 are a draft**
reconstructed from the README milestone table and HANDOFF scope notes — the owner
should review them before anyone treats the details as commitments.

| Milestone | Scope | Status |
|---|---|---|
| M1 | Parse (PDF, offsets, Thai), extract, verify evidence, retry, auth, upload API, web UI | ✅ done (2026-07-30) |
| M2 | Async worker + queue, OCR, DOCX, two-column fix, MinIO, PDF viewer overlay | ▶ in progress |
| M3 | Job requirements, hybrid retrieval, requirement-level judging, ranking | draft |
| M4 | Application state machine, idempotency, race conditions, RBAC, PDPA | draft |
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

## M2 — in dependency order (from HANDOFF §7)

- [ ] 1. ARQ worker + Redis; move `process_resume` off the request. It was written
  to be called from a job — takes no HTTP types, does not commit.
- [ ] 2. Job state, retry with backoff, dead-letter queue.
- [ ] 3. SSE progress endpoint; wire the web UI's "Parsing…" state to it.
- [ ] 4. OCR fallback for scans (Tesseract + `tha`). `ParsedDocument.pages_without_text`
  is the work list; `resume_scanned.pdf` / `resume_mixed_scan.pdf` are ready fixtures.
- [ ] 5. DOCX parser. `parse_document_bytes` already dispatches on extension.
- [ ] 6. Two-column fix via bbox column detection. The strict xfail in
  `api/tests/test_parse.py` defines "done".
- [ ] 7. MinIO storage backend. `build_storage` has the `MINIO` branch stubbed.
- [x] 8. Evidence viewer, text-layer only (`web/components/DocumentPane.tsx`).
  The true pdf.js overlay needs bbox geometry — do it with #6.

## M3 — matching engine (draft)

- Job/requirement models and CRUD: a job posting decomposed into individual
  requirements (skills, years, education, language).
- Hybrid retrieval over verified claims (BM25 + embeddings via pgvector — the
  compose file already runs `pgvector/pgvector:pg17`).
- Requirement-level judging: each requirement judged against cited evidence only,
  so every match/miss is explainable in the UI. The same quote-verification rule
  applies — a judgment that cannot cite evidence is dropped.
- Ranking across candidates from requirement-level results; ranking rationale is
  the list of citations, not a bare score.

## M4 — backend depth (draft)

- Application state machine (applied → screened → shortlisted → …) with
  transitions enforced server-side.
- Idempotency keys on submission endpoints; fix remaining check-then-act races.
- RBAC: candidate vs recruiter vs admin roles.
- PDPA compliance: consent capture at upload, data-retention policy, delete/export
  endpoints (the user-journeys spec calls for this explicitly).

## M5 — recruiter UI, observability, ship (draft)

- Recruiter views: job list, candidate list per job, requirement-level match
  breakdown with citation highlighting, dropped-claims audit view.
- Observability: structured logs shipped somewhere queryable, request metrics,
  cost dashboard from `llm_call_logs`.
- Deploy: containerize API + web, run compose stack in production mode, httpOnly
  cookie auth instead of localStorage.

## M6 — optional evaluation (draft, one-week timebox)

Ranking quality against a BM25/embedding baseline needs a labelled gold set.
Deliberately out of the critical path: the free metrics (hallucination rate, parse
success, cost per document) already ship in M1–M2. If the timebox expires, stop.
