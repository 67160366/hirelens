# Working notes

Short, dated notes from working sessions: what happened, what comes next, and
advice for the owner. Newest entry first. The detailed records stay in
`HANDOFF.md` and `PLAN.md` — this file is the quick version, with pointers.

---

## 2026-08-08 (latest) — screening lands, and M3 is usable over HTTP

Slice 3. A screening is now a row produced on the background worker, which is the
point at which the milestone stops being two disconnected halves: before this, jobs
lived in the database and judging was a pure function, and there was no way to ask
for a screening except through the CLI.

Suite **339 → 379**.

### The decision the rest of the slice hangs on

**`decide_retry` answers in intents, not statuses.** The obvious extraction — return
a status — fails immediately, because `Resume` and `Screening` do not share a
vocabulary: a screening is never `parsed` or `extracted`. Making them share one enum
would have leaked each table's states into the other for the sake of code reuse.

So the policy returns `PERMANENT` / `RETRY` / `EXHAUSTED` plus a reason and a
`JobOutcome`, and each job maps that onto its own statuses. `run_resume_job` behaves
identically and `tests/test_retry.py` passed untouched, which is exactly the guard
`PLAN.md` asked for.

### The fingerprint, which is the interesting design problem

A stored screening has to know when it stops answering the current question. Too
broad and it re-runs — and re-bills — screenings nobody changed; too narrow and it
serves a stale verdict as though it were current.

The rule: **hash exactly what the judge was shown.** Kind, label, detail, and their
*order* — the model refers to requirements by position, so a reorder is genuinely a
different question. And deliberately **not** `must_have` or `weight`, which never
reach the prompt at all. They are ranking's inputs, and a verdict cannot depend on
them; folding them in would mean every nudge of a weight spends a model call
reproducing an identical answer.

`prompt_version` is stored beside the hash rather than inside it, so "the
requirements changed" and "we changed the prompt" stay distinguishable — they call
for different conversations.

That rule shows up in the API as a status code: `POST /jobs/{id}/screenings` answers
**202** when it queued work and **200** when the stored result already answers.

### The consequence worth noticing

**A completed screening is re-runnable; an extracted resume is not.** `run_resume_job`
refuses an `extracted` resume because redoing it bills a second call for a profile we
already have and the document cannot change. A screening's requirements *can* change,
so the job does not refuse — the waste is prevented one layer up, in
`request_screening`. Two jobs that look like twins, differing on purpose, with the
reason written down in both places.

### Verified live, not only by tests

Through the containers against real Gemini, after rebuilding and confirming
`/openapi.json` lists the new routes:

- `POST` → **202**, the **ARQ worker** took it (job id `screening:…:0`), completed in
  4.1 s: **3/5 met, 0 dropped**, every citation slicing back out of the returned
  `document_text`.
- The Thai requirement `งาน Backend ที่เกี่ยวกับระบบชำระเงิน` matched the resume's own
  `ดูแลระบบกระทบยอดการชำระเงินด้วย Python และ PostgreSQL` — semantic matching in Thai,
  with an exact quote.
- `Kubernetes` and `ภาษาญี่ปุ่น` came back `not_evidenced` with **no evidence
  attached**, rather than asserted absent.
- Asking again → 200, nothing queued. Changing a **weight** → still 200, still not
  stale. Changing a **label** → stale, then 202 and a second dispatch under job id
  `screening:…:1`, `attempts=2`.
- In `psql`: 21 `extract-v1` rows all carrying `resume_id`, 2 `judge-v1` rows all
  carrying `screening_id`, none crossed.

### Worth knowing next time

- **`RecordingQueue` means the resume is never processed.** Half of the first test
  run failed as `NotScreenable` — not a bug in the code, a bug in the fixture: with
  the inline queue replaced, an upload only *queues* work, so `document_text` was
  never written. The helper now runs `run_resume_job` explicitly. Worth remembering
  because the failure message points at the feature, not at the setup.
- **A test helper with a named parameter cannot be overridden through `**kwargs`.**
  `spec("Python", label="Python 3")` is a `TypeError`, not an override. `model_copy(update=...)`
  is the version that works on a pydantic model.
- The two throwaway accounts from the live run were deleted, and the stack is left
  with `api` and `worker` **rebuilt from current code**.

### Advice for the owner

- **When two things rhyme, share the decision and not the vocabulary.** The retry
  policy was worth sharing; the status enum was not, and the version of this change
  that shared both would have looked tidier and been wrong. The test that would have
  caught it does not exist — `ScreeningStatus.PARSED` would simply have been a state
  nothing could ever reach.
- **A status code can carry a design decision.** 202-vs-200 on the same endpoint is
  how a client learns, without asking, whether its question was already answered.
  That is cheaper than a `stale` flag nobody reads and more honest than always
  re-running.

---

## 2026-08-08 — slice 1 is finally pushed, and judging lands

Three commits. The first was written last session and had been sitting in the
working tree ever since.

| | Commit |
|---|---|
| `e69677f` | Add jobs and the requirements a candidate is screened against |
| `0b3b830` | Store the page boundaries a stored quote maps back to |
| `2fb1f11` | Judge a requirement by the quotes that prove it, or not at all |

Suite **295 → 339 passing**, 26 skipped. `e69677f` is green on CI (run
`31247527205`) with the same 295/25 a local run gives, on a machine with no
Tesseract, no database, no MinIO and no API key.

### The thing to do first, again

Slice 1 had been verified against Postgres, against the containers and in a live
run — and was **committed nowhere**. `git rev-list --count origin/main..main`
answered `0`, which is the reading that matters: not "some commits are waiting" but
"CI has never seen any of this". Pushing it took four minutes and the answer came
back in one.

It also mattered *this* session specifically, because slice 2 modifies
`app/llm/fake.py`, which the entire suite depends on. Had that broken with slice 1
still uncommitted, the two failures would have been indistinguishable. **Push before
touching shared infrastructure, not after.**

### What landed

**`page_spans` first, as its own commit.** `resumes` stored `document_text`
verbatim but not where its pages ended, so a quote located in that text *later* —
which is exactly what judging does — had no way to name a page. `ParsedDocument`
gained `stored_page_spans` and `from_stored`, written next to each other because
they are the two halves of one round trip. The distinction worth keeping: the
existing `reparse_document` goes back to the *file* and, under a different OCR
configuration, can move every offset after a rescued page; `from_stored` parses
nothing and cannot. Not backfilled, for that same reason — pre-`0005` rows report
page 1, which is the honest answer for a row that never recorded its boundaries.

**Judging.** `pipeline/judge.py` + `schemas/judgment.py` as twins of
`extract.py` / `extraction.py`, reusing `EvidenceRef`, `DroppedClaim` and
`EvidenceStats` unchanged — which is why the hallucination rate covers judging
without a line of new metric code. `app/llm/fake.py` learned `RawJudgment`, not
optional: it raised for every other schema, so the suite and CI would have needed an
API key.

### Three decisions, and how each was checked rather than assumed

**1. The retry loop must NOT copy `extract_profile`.** Extraction keeps the attempt
with the fewest rejections. The judging retry prompt tells the model to *leave a
requirement out* rather than reword a bad quote — so a compliant second attempt can
answer about nothing, score zero rejections, and on extraction's rule **win**,
throwing away requirements the first attempt had proven with real citations.
`_is_better` prefers more `met`, then fewer dropped.

**2. A requirement is referred to by 1-based number, not UUID.** Cheaper in tokens
by an order of magnitude across 30 requirements, and — the real reason — a garbled
UUID is unrecoverable while an out-of-range integer is catchable. It becomes
`RejectReason.UNKNOWN_REQUIREMENT`: pointing at a requirement that does not exist is
the same class of claim as quoting text that is not there. Duplicate numbers merge
instead of overwriting, which would lose verifiable evidence silently.

**3. The requirement list goes outside `<resume>`.** `fake.py` finds the document by
that exact block, so a list inside it gets quoted as though it were the resume.

All 32 tests passed on the first run, which is the point at which this project's own
advice says to stop and ask whether they *could* have failed. So each of the three
decisions was reverted in a throwaway pytest plugin and the real suite re-run:
**1, 3 and 4 cases fail** respectively. The tests defend the decisions rather than
describing them. That is twenty minutes well spent, and it is the cheap version of
the habit the fixture lessons keep teaching.

### Verified by running it

- Migration `0005`: `upgrade head` → `downgrade -1` → `upgrade head` on real
  Postgres, `alembic check` clean, and `page_spans` confirmed `jsonb` **in `psql`**
  rather than inferred from a green suite.
- **Live Gemini, `resume_th.pdf`**: a requirement typed as
  `ปริญญาตรีวิศวกรรมคอมพิวเตอร์` matched the document's own, differently worded
  `วิศวกรรมศาสตรบัณฑิต สาขาวิศวกรรมคอมพิวเตอร์` — real semantic matching with an
  exact quote. And `ประสบการณ์ Backend อย่างน้อย 3 ปี` came back `not_evidenced`,
  because the resume never states a total: the never-infer rule holding on a
  question it would have been easy to answer wrongly.
- **`resume_multipage.pdf` judged through `from_stored`** — stored text plus stored
  spans, no file read — cited on pages 2 and 3 with every span slicing back out
  exactly. That is the screening path end to end, minus the row slice 3 adds.
- The CLI's old path: three fixtures, before and after, **identical** output.

### The cleanup pass at the end of the session

Three things were fixed after slice 2 was pushed, each because it was tractable now
rather than because it was urgent.

**The running containers had drifted behind the code.** `alembic upgrade head` ran
from the host, so the *database* had `page_spans` while the `api` and `worker`
images were two hours old and their `Resume` model did not — meaning the worker
would have written `NULL` into a column that exists. Nothing would have failed
loudly; the spans would simply have been missing. Found by asking the container
directly (`'page_spans' in Resume.__table__.c` → `False`) rather than by reasoning
about it. **A migration applied from the host does not update a running container**,
and this stack now has two places code can be stale.

Fixed with `docker compose up -d --build api worker`, then verified by uploading
through the real stack: `resume_multipage.pdf` got 3 spans for 3 pages, and
`resume_th.pdf` came back 10/10 verified with the last span's `char_end` equal to
`length(document_text)` exactly — read out of `psql`, and the throwaway accounts
deleted afterwards.

**`_reference` is no longer duplicated.** `pipeline/verification.py` holds
`EvidenceRecorder`, used by both `extract.py` and `judge.py`, and it absorbed
judging's `UNKNOWN_REQUIREMENT` path too. The reason it needed a *new module* rather
than a moved function is the reason it was deferred: it wants `pipeline.evidence`
and `schemas.profile`, and `schemas.profile` already imports `pipeline.evidence`.

**One npm advisory closed.** `npm audit fix` fixes nanoid with a lockfile bump; 4
high → 3. postcss and sharp both need `next@16`, a framework major, and were left.

**`tests/test_judge_live.py`** closes the gap this session reported: the fake matches
a requirement label by substring, so under it a requirement worded differently from
the document *always* reads `not_evidenced` — and real screening is mostly that case.
Twelve cases against the real provider, shaped like `test_postgres.py` and
`test_minio.py`.

The gate is `TEST_LIVE_LLM=1`, **not** the presence of a key. That distinction is the
whole design: `.env` on any development machine already holds a real Gemini key, so
gating on the key would have turned every `pytest -q` into a billed run — the exact
opposite of the property §2 of the handoff calls load-bearing.

It was checked the same way as everything else this session: pointed at the fake
provider, **exactly the three semantic-matching cases fail** and the other nine pass.
That partition is the useful part — nine of the twelve assert things that must hold
for *any* provider (every span slices back out, no `met` without evidence, the
numbering contract survives, absence is never asserted), so they are worth running
against a new provider on day one.

### A check that silently proved nothing

The refactor was verified by diffing CLI output before and after — except the first
attempt stashed three files, one of which was untracked, so `git stash` refused the
whole thing and **both sides of the diff came from the new code**. It printed
`IDENTICAL` and meant nothing.

The tell was in the output the whole time: `No stash entries found` scrolled past
above the result. This is the same failure as `git hash-object` and the Thai
mojibake, in a new costume: *the instrument answered a different question than the
one being asked.* Worth adding to the habit — when a check passes, confirm the check
actually ran, not just that it printed success.

Redone properly (stashing only the two tracked files, checking `git diff --stat`
showed them reverted): extraction and judging output byte-identical over four
fixtures, and the three judging mutations still fail 1/3/4 cases.

### Still open, in order

1. **Slice 3 — screening as a row on the worker.** `HANDOFF.md` §9 lists four things
   to know first, including two that are easy to get wrong: a judging call must log
   `JUDGMENT_PROMPT_VERSION`, and `requirements_hash` should cover what the judge
   actually saw (kind, label, detail, order) but *not* `must_have`/`weight`, which
   are ranking's inputs.
2. Slices 4–6: ranking, the thin UI, retrieval.
3. The visibility timeout for a worker that dies mid-job (M5) is still the last §11
   follow-up, and is the only open item that can strand a user's data with no way
   back through the API.
4. Next 15 → 16 for the remaining postcss and sharp advisories. A framework major;
   belongs with the web work, not squeezed in.

### Worth knowing next time

- **The fake quotes the whole line a label sits on, not the label.** Real skills are
  short — "Go", "AWS", "SQL" — and `MIN_QUOTE_CHARS` is 4, so quoting the label would
  reject legitimate requirements before they ever reached a verdict.
- `ruff format` and the E501 rule can disagree about a long test name; run the
  formatter *after* the last edit, not before.

### Advice for the owner

- **The "could this have failed?" habit now has a cheap mechanical form.** Writing a
  ten-line pytest plugin that reverts one decision, then running the real suite
  against it, answers in seconds what staring at a green tick never will. Worth doing
  for any decision documented as deliberate — if reverting it fails nothing, either
  the decision or the test is decorative.
- **Notice when a rule from one module stops applying in the next.** Judging looks
  like extraction everywhere except the one place it must not be, and copying
  `extract_profile`'s tiebreak would have produced a system that quietly discarded
  proven evidence. Twins are worth writing; twins are also worth diffing.
- **Confirm the check ran, not just that it passed.** The stash that refused an
  untracked path printed `IDENTICAL` while comparing the new code with itself. Every
  previous instrument lesson here was about a tool answering the wrong question; this
  one is about a tool not running at all and the harness reporting success anyway.
  Cheap defence: make the check *fail* once on purpose before trusting it — the same
  habit as building the adversarial fixture first.
- **The stack now has two places code can go stale**, not one. A migration run from
  the host updates the database while the containers keep their old models, and the
  symptom is a column that exists and is never written. `docker compose up -d --build
  api worker` after any model change, and ask the container what it thinks rather
  than assuming.

---

## 2026-08-08 — M3 is scoped, and its first slice lands

M2's handoff asked for one thing before any M3 code: **review the scope, because
`PLAN.md`'s M3 was a draft reconstructed from the README rather than a set of
commitments.** That review happened this session, four questions were settled with
the owner, and the first slice shipped against the agreed shape.

### The four calls, and why each one went the way it did

| Question | Decision |
|---|---|
| Where hybrid retrieval sits | **Last slice.** The suite runs on in-memory SQLite and must keep doing so; pgvector is Postgres-only and embeddings need a provider *and* a price table. Lexical is the no-server default behind a `Retriever` seam, pgvector opt-in |
| Verdict vocabulary | **`met` / `not_evidenced`** |
| Where requirements come from | **Typed in through CRUD.** A requirement is an input, not a claim about a person — putting a model in front of it adds a failure mode without adding a guarantee |
| UI in M3 | **A thin one.** Two features shipped in M2 without a human ever seeing them rendered; the full recruiter UI still waits for M5 |

Plus three taken by default: a job is owned by a `Candidate` row (M4's RBAC widens
*who* without changing the table), a screening is a first-class row that **shares**
the retry policy rather than copying it, and `resumes.page_spans` gets stored so a
judgment quote maps to a page without re-parsing.

### The idea the whole milestone hangs on

**The model is never asked for a verdict.** It is asked only for quotes showing a
requirement is met, and to omit the requirement otherwise. The application derives
the rest: one quote that resolves is `met`, nothing that resolves is
`not_evidenced`, and every quote that failed lands in `dropped` and in the
hallucination rate.

That is the same move as never asking for offsets, applied to judging — the one
thing a model could assert unverifiably ("this candidate does not have X") it is
never given the chance to say. It is also simply the honest label: the system
cannot tell "the candidate lacks it" from "the resume does not mention it", and
`not_met` would claim it can.

### What landed

Slice 1 — **jobs and requirements as rows, with CRUD**. `app/models/matching.py`,
`app/api/routes/jobs.py`, migration `0004`, `tests/test_jobs.py`. Suite
**270 → 295 passing**, 25 skipped. Requirement routes are nested under their job so
ownership is settled in one place, every lookup answers **404 rather than 403**, and
the list is capped at 30 because all of it travels in one judging prompt.

### Three defects and one false alarm, none of which a passing test would show

**1. An empty requirement list raised `MissingGreenlet`.** Creating a job *with*
requirements worked; creating one without them blew up. The reason is that
appending to `job.requirements` is what marks the collection loaded — leave it
alone and rendering the response lazy-loads it *after* the commit, which on an
async session is an error rather than an empty list. Fixed by passing the list to
the constructor. Worth remembering as a shape: **the happy path was hiding the
bug, because the happy path did the initializing.**

**2. A check constraint spelled out in full gets wrapped twice.** `ck` is the only
convention in `models/base.py` that interpolates `%(constraint_name)s`, so
`name="ck_job_requirements_weight_positive"` in the migration became
`ck_job_requirements_ck_job_requirements_weight_positive` in the database, and
`alembic check` reported drift against the model *forever*. The fk/pk/uq names in
the same migration are safe spelled out — their conventions never reference the
given name. Found by `alembic check`; `pytest -q` was green throughout.

**3. `RequirementKind` persists as enum *names*.** A `WHERE kind = 'language'`
query returned zero rows against data I had just watched go in. SQLAlchemy stores
`LANGUAGE` while the API serializes `language` — the same split `HANDOFF.md` §7
already records for `ResumeStatus`. The migration now declares the upper-case forms
instead of repeating `0001`'s misleading value list.

**4. Not a defect: PowerShell mangled the Thai.** The live check printed
`à¸ à¸²à¸©à¸²à¹à¸à¸¢` where `ภาษาไทย` belonged. PowerShell 5.1 decodes a JSON response
body as Latin-1 unless the server names a charset. Postgres said 7 characters, 21
bytes — stored perfectly. **Same class as `git hash-object` lying about CRLF
damage: the instrument was answering a different question than the one being
asked**, and the only way to tell is to go to the authoritative store.

### Verified by running it

- Migration `0004`: `upgrade head` → `downgrade -1` → `upgrade head` on real
  Postgres, `alembic check` clean.
- The check constraint refuses `weight = 0` **on Postgres**, not only in the tests.
- The API container was **rebuilt before being believed**, and `/openapi.json`
  lists the four `/jobs` routes — the standing rule about zombie servers, and the
  reason the run means anything.
- Live: create a job with four requirements → read it back → a second account gets
  404 → `weight: 0` gets 422.

### Still open, in order

1. **Slice 2 — requirement-level judging.** The load-bearing piece inside it is
   `app/llm/fake.py`: it raises for any schema that is not `RawExtraction`, so
   until it can answer `RawJudgment` the whole suite and CI would need an API key.
2. Slices 3–6: screening on the worker, ranking, the thin UI, retrieval.
3. Slice 1 is **committed nowhere yet** — it is in the working tree. Push in small
   batches, as every previous entry says.
4. The visibility timeout for a worker that dies mid-job (M5) is still the last §11
   follow-up.

### Worth knowing next time

- **`pytest -q` cannot see a migration.** Two of this session's three defects were
  invisible to the gate and visible to `alembic check` and one `psql` query. A new
  table is not verified until it has round-tripped on Postgres and been queried
  there.
- The stack was left running with `api` and `worker` **rebuilt from current code**,
  and the throwaway accounts and jobs from the live check were deleted afterwards.
- `HTTP_422_UNPROCESSABLE_ENTITY` is deprecated in this Starlette;
  `HTTP_422_UNPROCESSABLE_CONTENT` is the name now.

### Advice for the owner, going into the rest of M3

- **Ask what instrument you used, every time — it keeps paying.** That advice was
  written two sessions ago about `git hash-object` and it caught the Thai scare
  today inside a minute. The habit is cheap: when a check says something surprising,
  suspect the tool before the code, and go to the store that cannot lie.
- **Verify the empty case on purpose.** The `MissingGreenlet` bug existed only for a
  job with no requirements — the case nobody demos. Every list, every optional
  field, every collection: try it empty before believing it works.
- **The verdict decision is the one worth refusing to trade.** If someone later asks
  for `not_met` because it "reads better in the UI", that is the moment this project
  turns into a scoring system whose numbers nobody can check. `not_evidenced` is
  less satisfying and it is what the system actually knows.

---

## 2026-08-08 — M2 is closed

Seven commits, **pushed and green on CI** (runs `31240368969` and `31240479417`).
The two remaining M2 items shipped (#6 two-column, #7 MinIO) and three items came
off the watch list with them.

| | Commit |
|---|---|
| `cc4721c` | Bump the CI actions off Node 20 |
| `5b6f8c8` | Read a two-column page one column at a time |
| `cbad6ad` | Store uploads in MinIO behind the same interface |
| `6b8194b` | Reject a scan Tesseract could not read with confidence |
| `023468a` | Add a PDF that is broken on purpose |
| `dc6f470` | Close M2: refresh the handoff and the plan |
| `6ec8240` | Pin setup-uv to a release that actually runs on Node 24 |

Suite **214 → 270 passing**, 25 skipped (4 Postgres + 12 Tesseract + 9 MinIO, all
opt-in), and **no xfail left** — the two-column one did its job. CI reports the
same 270/25 on a runner with no Tesseract, no database, no MinIO and no API key,
which is the whole point of the opt-in split: three system dependencies now, and
`git clone && pytest -q` still works on a bare machine.

### Three findings that changed the design

Each of these came from measuring something before building on it, and each one
would have produced a plausible-looking wrong implementation if skipped.

**1. A column profile over the whole page finds nothing on a real two-column
resume.** The committed fixture has no header, so a projection profile splits it
cleanly and the naive approach looks correct. Add the full-width header every real
two-column resume has, and the header line spans the gutter and hides it. The fix is
to cut *horizontally* first — bands — and look for a gutter inside each one. This is
why the new `resume_two_column_header.pdf` exists: the old fixture could not have
caught it.

**2. Tesseract's TSV output destroys Thai.** The obvious way to add a confidence gate
is one invocation with `tsv`, which gives per-word confidence *and* the text. But TSV
tokenizes Thai per glyph, so `ทักษะ` comes back as six "words" and a line rebuilt from
them reads `ท ั ก ษ ะ` — spaces between a character and its tone mark, in the string
that becomes `document_text` with every evidence offset pointing into it. So the gate
costs a second invocation. Measured before writing the code, not discovered after.

**3. Removing `/ToUnicode` does not reproduce the §11 NUL bug.** pdfminer falls back
to `(cid:1)(cid:2)...` placeholders — a different defect. The damage has to be *in*
the map: a well-formed CMap that says a glyph means U+0000. That is why the fixture is
hand-written rather than made with reportlab, which only ever writes correct maps.

### The one number worth remembering

`OCR_MIN_CONFIDENCE=75`. Degrading the scanned fixture sixteen ways: everything that
still yielded its content scored **90.2 or better**, everything that yielded none
scored **47.4 or worse**. The full table is in `HANDOFF.md` §7, and
`tests/tools/ocr_degradation.py` is committed this time so it can be re-run rather
than re-derived. It is tuned on one clean synthetic render, which is its main
weakness — a real photograph will score lower while still being readable.

### The property most worth not losing

Column detection returns `None` for anything it is not confident about, and `None`
is the *old code path*. Verified by parsing every fixture twice, with detection on
and forced off: byte-identical everywhere except the two two-column documents, which
were reordered with the same words present. That is what keeps every citation already
shown to a user pointing where it did, and any future change to `layout.py` should be
checked the same way.

### A bug found by pushing, which is the argument for pushing

The commit called "Bump the CI actions off Node 20" **only got two of the three**,
and nothing local could have told me. CI's own annotation did: `setup-uv@v6` was
still being force-run on Node 24.

The reason is worth knowing before the next actions bump. `@v6` *was* the newest
floating major tag — but setup-uv **stopped publishing floating majors at v8 on
purpose**, because a moving `@vN` is exactly what made the tj-actions supply-chain
attack possible. Their releases are immutable instead, and the recommended form is a
pinned release. So "reach for the next `@vN`" silently gave the newest tag that was
two majors stale, and the deprecation it was supposed to fix survived. Fixed by
pinning `@v9.0.0`; the annotation is gone.

**The general lesson:** *a version bump that still emits the warning it was meant to
remove has not worked.* Read the annotations on the run, not just the green tick.

### Still open

1. **The browser has not seen either new feature.** A two-column resume rendering in
   `DocumentPane` is the cheapest outstanding check.
2. **M3.** Its scope in `PLAN.md` is still a draft — review it before building to it.
3. The visibility timeout for a worker that dies mid-job (M5) is the last §11
   follow-up left.
4. `prune-cache` now defaults to false in setup-uv v9, so the Actions cache will
   grow. Harmless on a repo this size; worth remembering if cache limits ever bite.

### Worth knowing next time

- **The stack was left back on `STORAGE_BACKEND=local`**, matching `.env`, and the
  worker log confirms `storage=local`. MinIO was verified with
  `STORAGE_BACKEND=minio docker compose up -d --build` — an env var on the command
  line rather than an edit to `.env`, so there was nothing to restore afterwards.
  Restoring it anyway was deliberate: a running stack that disagrees with the config
  file is the same class of trap as the zombie server and the stale worker, and this
  project has already lost time to both. **Note the bucket keeps its objects**, so
  flipping back to `minio` later finds the earlier uploads still there.
- **Git Bash mangles container paths.** `docker compose exec api find /data/uploads`
  becomes `C:/Program Files/Git/data/uploads` inside the container. Use PowerShell
  for `docker compose exec`, or `MSYS_NO_PATHCONV=1`. Cost ten minutes.
- **`git hash-object` still lies about CRLF damage** (previous entry), and
  `uv.lock` must be regenerated whenever `pyproject.toml` changes or CI's
  `uv sync --locked` fails the build.

### Advice for the owner, going into M3

Previous entries' advice all still stands — this is what *this* session added.

- **Test the fixture before trusting the feature.** Three times now, the fixture has
  been the thing that was wrong: the CRLF-corrupted PDFs, the two-column fixture with
  no header, and the first right-aligned-dates fixture, which was so sparse it was
  genuinely ambiguous rather than a fair test. A fixture that passes tells you
  nothing until you have asked whether it *could* have failed. The habit worth
  keeping is the one that caught all three: build the adversarial case first, watch
  it fail, and only then write the code that fixes it.
- **Measure the thing you are about to build on.** Every design decision in this
  session that survived contact came from a five-minute measurement first — the
  gutter geometry, the TSV/Thai finding, the ToUnicode experiment. Each would have
  produced a plausible, wrong implementation if skipped, and two of them would not
  have been caught by any test I would have thought to write.
- **Keep the `None` habit for M3.** The reason the two-column change was safe to
  ship is that it is inert on everything it does not understand, and that was proven
  by parsing every fixture twice and diffing. M3's judging layer wants the same
  shape: a requirement that cannot be judged from cited evidence produces *no*
  judgment rather than a low-confidence one. `dropped` already exists for exactly
  this, and the guardrail generalizes for free.
- **M3 is the first milestone where the model's output is not just extracted but
  compared.** Guard the line: a match/miss must cite evidence the same way a claim
  does, or the project quietly becomes a scoring system whose numbers nobody can
  check. That is the one design constraint worth refusing to trade away for
  throughput.
- **Don't let the browser check slip again.** It slipped for two sessions before,
  and both features shipped this time without a human ever looking at them rendered.
  It is fifteen minutes.

---

## 2026-08-08 — the whole stack runs in containers

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
