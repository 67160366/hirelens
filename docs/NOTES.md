# Working notes

Short, dated notes from working sessions: what happened, what comes next, and
advice for the owner. Newest entry first. The detailed records stay in
`HANDOFF.md` and `PLAN.md` — this file is the quick version, with pointers.

---

## 2026-08-20 (latest) — two trust defects watched, both slices pushed, and the UI becomes the priority

**Both slices are committed and pushed** (`716cda1..443e947`), and CI run **32332606027**
is green on both jobs with **0 annotations** — read through the API rather than off the
tick, and it is the first clean-runner build of the IBM Plex swap. The working tree is
clean. Two commits rather than the three the plan named: `RankingTable.tsx` and
`app/page.tsx` carry hunks belonging to both A and B, and splitting them with `git add -p`
against a usage limit risked leaving a broken intermediate commit — so A and B landed
together, with the commit message naming both halves and saying what had not been
watched.

Both of last session's blockers were gone before the first command: the **Chrome extension
is connected**, and the dev server on :3000 was healthy (its 00:11 parse error was a
mid-edit state, compiled clean at 00:12). There is **no `web` container** — :3000 is
`npm run dev` serving the working tree directly, so no rebuild stands between the code and
the browser, and the usual "is the container serving the new bundle?" trap does not apply.

Gates re-run first, because group D landed after the last full run: `typecheck` clean,
`lint` clean, vitest **168**. Nothing under `api/` touched, so `pytest` was not re-run.

Driven on `LLM_PROVIDER=fake` — **zero Gemini quota**. Console instrument proven to speak
first (a `console.log`/`console.error` probe pair, both confirmed visible) before any
absence was believed.

| Check | Result |
|---|---|
| **A1 — switching candidates with the Original tab open** | `resume_th.pdf` renders its PDF with **4** citation boxes (widths 126.25 / 25.30 / 13.77 / 42.22). Selecting `resume_en.pdf` renders a visibly different document (`Somchai Jaidee`, Latin) with **8** boxes of entirely different widths, on the English quote line. Switching back reproduces the Thai four **exactly**. No stale bytes, no stale geometry |
| **A1, the mechanism** | The pane returns to *Extracted text* on every switch — `key={selected.screening_id}` remounting the provider. So the `loadedFor` ref is defence in depth rather than the visible half, which is worth knowing before anyone "simplifies" either guard away |
| **A2 — two fast clicks on ranked rows** | **The race was forced rather than hoped for**: `fetch` patched so the `resume_th` screening answered **4 s late**, then th and en clicked 76 ms apart. Console confirms both requests fired and that **th's late answer genuinely arrived**. The screen still reads `resume_en.pdf`, the English `document_text`, and the English quote at `p1 · chars 150–213 · exact`. The stale answer was dropped |
| **A2, why the remount does not cover for it** | `detail` is state on the *page*, not inside the keyed subtree, so a late `setDetail` would have landed regardless of the remount and paired en's verdicts with th's text. The `requestedScreeningId` guard is what does the work |
| **A4 — the served filename** | The ranking table names `resume_th.pdf` / `resume_en.pdf` from `RankedEntry.resume_filename`, with no client-side join |
| **A3 — `/applications` history keyed by id** | Passed, and **no throwaway account was needed**: `applications.py:164` says applying is *"open to any role"*, so the recruiter authored a second posting and applied to both. The sharp half was driven — `fetch` patched to fail the *second* history request — and the row read **"Loading the history…"** with a red banner, **not** the first row's timeline, which is the state that used to persist. On the success path the two logs carry different timestamps (`11:51:52` vs `11:52:10`), so they are genuinely two logs rather than one leaked between rows |
| **B1 — `.docx` in the picker** | `accept` carries both MIME types and both extensions |
| **B2 — the consent label split** | Two separate labels; the consent one contains only the checkbox and the file one contains neither. Clicking the consent **text** ticks the box and unlocks the picker rather than opening a file dialog. Consent unticked on load, picker `disabled` — the 2026-08-13 property, still holding |
| **B3 — error and retry on `/jobs`** | Forced with a patched `fetch`: the banner names the API and the list area reads **"The list of jobs could not be loaded. [Try again]"**, where it used to be silently empty — indistinguishable from "you have no postings". "Try again" then recovered |
| **B4 — the ranking table from a keyboard** | Both rows are real `<button>`s at `tabIndex 0`, all five headers carry `scope="col"`, the wrapper is `overflow-x: auto`. **Enter on the focused button selected the candidate**: `aria-expanded` → `true`, `aria-current` on its row, the evidence pane opened, and focus stayed on the button |
| **B4 settles the `aria-current` question** | It sits on a `<tr>` nothing can focus — but the focusable `<button>` carries `aria-expanded`, so the selected state *is* announced on the element that receives focus. **Not a defect.** The smell recorded earlier is closed |
| **B5 — the two-step delete** | Reads *"Delete "Kubernetes"? 2 screenings become stale and have to be run again — one model call each."* with Delete / Cancel. Cancelled rather than confirmed; the requirement survived |
| **B6 — the `ResizeObserver`, the one item only a browser can check** | Passed, with the ratio as the proof. Pane 495.14 → 265.80, canvas **followed** 495 → 265, boxes 126.23 → 67.57 etc — and each box held its **fraction of the pane** (0.2549 → 0.2542), which is what "still on its text" means. Restoring the width reproduced the baseline **exactly**. A frozen scale would have left the boxes at their old widths on a re-rendered canvas |
| ⚠️ **An instrument lied — the twelfth** | `resize_window` **reported success and did nothing**: `innerWidth` stayed 2133 across a 2133 → 1200 call. Reporting "the observer is inert" off that would have been a defect filed against working code, because the *input never changed*. Driven instead by squeezing the ancestor of the element `ResizeObserver` actually watches |

**Instrument note, unchanged and still costing time:** the extension reports a viewport of
**2133×987** while screenshots come back **1568×726**, so a coordinate click lands in the
wrong place — the first click of the session missed by ~115 px. Drive with refs.

### The owner reset the priority: the UI comes first

Said at the end of the session, and it reorders everything below. The screens still look
like the internal tool they started as — **monochrome, undesigned** — and making them not
look like that is now the most urgent work rather than the last. Three requirements, in
the owner's words: **colour**, **animation**, and a style that is **formal but modern**
(*ทางการแบบทันสมัย*). The style choice is delegated rather than specified. And **a mockup
is wanted before any real screen is built.**

**This does not replace `docs/DESIGN.md` — it explains why none of it is visible yet.**
The palette already carries colour (indigo `accent` plus the three reserved meaning
colours) and the motion doctrine already names four animations. Nothing renders in any of
it because **no page has been migrated onto the tokens**: every screen is still on its
~300 hand-typed `dark:` utilities, and `web/components/ui/` has five primitives with zero
callers. So "it is black and white" and "the migration has not happened" are the same
fact, and the mockup is where *formal but modern* gets judged before it costs any code.

One tension to settle at the mockup and not in a stylesheet: `DESIGN.md` refuses gradient
heroes, glassmorphism and glow, and reserves three colours so nothing the product asserts
can be mistaken for a control. "Modern" must be delivered **inside** that constraint —
through type, spacing, density, elevation and motion — or the constraint has to be
renegotiated deliberately, in the open, rather than eroded one screen at a time.

**Tools to use, checked against what is actually available in this session:**

| Tool | For |
|---|---|
| `design` (Claude Design) | The mockup. A pan/zoom canvas of `.dc.html` artboards published as an editable Artifact. **This is where the look is decided**, before Next.js. A canvas from 2026-08-19 already exists (five artboards, precision-instrument) and is the starting point, not a blank page — edit it by reading the published page back with `--extract` |
| `artifact-design` | Must be loaded before writing any artifact, Markdown included |
| `artifact-diagramming` | The locate-then-keep explainer on "how we screen" |
| `dataviz` | **Required before any chart.** `/metrics` has tokens, latency and hallucination figures |
| `claude-in-chrome` | The only instrument that can judge the result in the real app. Connected as of this session |
| `run` | Launching the app; `npm run dev` on :3000 already serves the working tree |

No plugin beyond the installed skills is needed, and none was added. Deliberately unused:
`code-review`, `simplify`, `security-review`, `schedule`, `loop`, `claude-api`,
`update-config`, `init`.

**Do not fan out to subagents or workflows for this.** Design is one continuous judgment
call over material already in context; each spawned agent starts cold. Recorded once
before and worth not relearning.

### Next step, in order — revised by the owner's reset

**Fixes first, then something to look at, then the real screens.**

1. ~~**Finish A3 and the six B items in the browser.**~~ **Done, and one defect came out
   of it.** Everything above passed. The find was not on the screen at all: the two-step
   delete promised *"2 screenings become stale"* against a job whose two screenings both
   happened to be `completed`, so the browser **could not** show the bug — the API
   docstring did. `GET /jobs/{id}/screenings` returns the raw list *"including the ones
   still running and the ones that failed"*, and the page passed `screenings.length` into
   a prop documented as *"Completed screenings"*. A pending screening has spent no model
   call and a failed one produced no result, so the confirmation attached too high a price
   to a destructive action. `countCompletedScreenings` in `lib/screening.ts` now, three
   cases, two of which fail under mutation. **The lesson is the shape of the find**: a
   browser check found it by making it *look at* the sentence, not by making the sentence
   wrong — the number was right for this data and wrong in general, and only the
   contract behind it could say so.

2. **A mockup, before any screen code.** Formal-but-modern, in colour, with the four
   motions actually moving, on the tokens that already exist. Shown for approval as a
   published canvas, iterated with the owner, and only then translated into the primitives
   in `web/components/ui/`.
3. **Then the real screens**, one per commit, and none of them done until driven at
   375 / 768 / 1440 in **both** themes.
4. **Everything else waits behind those**: recording the careers-site direction and the
   Thai-first decision in `docs/PLAN.md` (it still ends at M6), and the eleven-slice
   careers-site build.

**The two smells found while reading B's code are both settled:**

- `screeningCount` — **confirmed a defect and fixed**, above.
- `aria-current` on an unfocusable `<tr>` — **not a defect.** The focusable `<button>`
  carries `aria-expanded`, so the selected state is announced on the element that takes
  focus. Watched flipping to `true` on an Enter press.

**One imprecision left deliberately, so it does not read as an oversight:** when a history
request *fails*, the row renders "Loading the history…" while nothing is loading. The red
banner beside it names the real cause, and the alternative the fix replaced — the previous
row's timeline — was far worse, which is what the code comment argues. Saying "Could not
load this history" instead needs a per-application error map rather than a per-application
event map, so it is a real change and not a wording tweak. **The owner's call, not one to
make while passing through.**

---

## 2026-08-19 → 08-20 — a direction, and the UI work it implies, started

**Nothing is committed.** Everything below is uncommitted in the working tree, and the
session was cut short before any of it was watched in a browser. This entry is the
record rule 7 in `CLAUDE.md` asks for.

The session began as a competitive question and became a direction decision.

**1. Where HireLens actually sits.** Not among job boards (JobsDB/SEEK, JobThai,
JobTopGun) but in **AI screening / matching**, beside Manatal (Bangkok), Findem and
Sapia. The differentiator nobody in that market claims is **locate-then-keep**:
competitors ship model-generated justifications, and none verifies that the quoted text
exists in the document or publishes a hallucination rate. The regulatory tailwind is
real — EU AI Act Annex III makes CV screening high-risk, Art. 26(11) requires telling
candidates and Art. 86 gives them a right to an explanation; NYC Local Law 144 requires
bias audits — and HireLens has the explainability half of that and none of the audit half.

**2. An audit of `web/` found 119 issues, 8 blocking.** Three of them make the product
state something false about a person, and are fixed below.

**3. The shape was decided:** a careers site whose employer is HireLens itself, with the
screening system as a **published feature** rather than a hidden back office, organised
around a **Screening Receipt** the applicant can open. That closes the founding pain
point (`README.md:8-9`) instead of decorating around it — and the position is already in
the code: `privacy_service.py:116-117` says a verdict about you is yours to see, so it is
exportable and merely not viewable. The full plan, with 11 slices and the refusals, is in
this session's plan file, kept outside the repo.

**4. The visual direction the owner chose is "precision instrument"** — ink and paper,
one indigo accent for actions, and the meaning colours (cited / ambiguous / dropped)
reserved, so nothing the product *asserts* can be mistaken for a button. Motion explains
the mechanism rather than decorating it. This **replaces** the conservative design system
originally scoped.

### What is in the tree

**A. Three trust defects, plus the filename the server already serves.** Each verified by
reading the code rather than taken from a report.

- `DocumentViewer.tsx` guarded on `file !== null`, so selecting a second candidate with
  the Original tab open drew **that candidate's citation boxes onto the previous
  candidate's PDF**. Now a `loadedFor` ref compared against `resumeId`, cleared before the
  fetch.
- `select()` in `app/jobs/[id]/page.tsx` awaited with no cancellation, so two quick clicks
  paired one candidate's verdicts with another's `document_text`. Now guarded by a
  `requestedScreeningId` ref, and the pane is keyed on `screening_id` so it remounts.
- `app/applications/page.tsx` held **one** events array for the whole page, so one
  person's rejection reason rendered under another's job title — permanently, if the
  request failed. Now keyed by application id.
- `RankedEntry.resume_filename` is served (`schemas/ranking.py:53,64`, with a docstring
  saying why) and the client re-derived it anyway. Now used, through `resumeLabel()`.

**B. Six standalone UX fixes** — `.docx` accepted by the file picker; the single `<label>`
that wrapped both the consent checkbox and the file input split apart; a real error state
with a retry on `/jobs`; keyboard access, `scope="col"` and horizontal scroll on the
ranking table; a two-step requirement delete naming how many screenings go stale; and a
`ResizeObserver` on the PDF overlay, which computed scale **once**, so every citation box
landed off its text after a resize.

**C. The design system, begun and not yet applied.** `app/globals.css` rewritten as
tokens — palette, type steps, radii, motion curves, `@utility` recipes. `app/layout.tsx`
finally loads Inter, IBM Plex Sans Thai (`thai` subset) and JetBrains Mono through
`next/font`: the stylesheet had named them since M1 and served none, so on Windows
everything fell through to Segoe UI, **which has no Thai glyphs**. Plus `lib/cn.ts` and
`components/ui/{Card,Button,Banner,Badge,Stat}.tsx`.

Gates on the last full run: `typecheck` clean, `lint` clean, vitest **165 → 168**. Nothing
under `api/` was touched, so `pytest` was not re-run. **No page has been migrated onto the
tokens yet** — the primitives are unused and every screen still renders on its ~300
hand-typed `dark:` utilities.

**D. The design foundation** — written after the token work, because the token work had
started at the wrong end. `docs/DESIGN.md` is new and is what the redesign now answers to:
the one rule (colour carries meaning before style — `cited` / `ambiguous` / `dropped` are
reserved, and `accent` is a different hue on purpose so nothing the product *asserts* can
be mistaken for a button), the typography decision, a measured contrast table, the motion
doctrine, the accessibility floors, and what is refused.

Two corrections to what this same session had already committed to the tree:

- **The typeface pairing was wrong.** Inter beside IBM Plex Sans Thai is two different
  x-heights in one line. IBM Plex Sans is the Latin companion Plex Thai was drawn against,
  so the whole superfamily is loaded now — Plex Sans, **Plex Sans Thai Looped** (the
  conventional Thai reading form for body text) and Plex Mono. Verified served: 31
  `@font-face` rules, with Inter and JetBrains gone.
- **`ink-faint` measures 4.59:1** on paper. It passes AA and it is the tightest value in
  the palette — and it was what the *smallest* text used. The citation coordinate line
  moved to `ink-muted` (7.30:1), which is free. Every other token clears AA in both themes;
  the table is in `DESIGN.md` and the computation is repeatable.

**A design canvas was published** — five artboards in the precision-instrument direction:
landing, public posting, the **Screening Receipt**, the recruiter workbench, and the
how-we-screen explainer. It is built on the same tokens as the code and it is clickable
rather than static: selecting a requirement sweeps its quote into place in the document
beside it, and the explainer toggles a faithful model against a fabricating one so the
strike-through is watched being drawn. Link:
<https://claude.ai/code/artifact/370834a7-f7a8-4bde-837c-67254cc2552a>

The canvas working files (`*.dc.html`, `canvas.json`, `build.mjs`) live in the session
scratchpad, deliberately not in the repo. A later session edits the canvas by reading the
published page back with the `design` skill's `--extract`, not by hunting for those files.

### Next step

In order, and the first one blocks the rest:

1. **Reconnect the Chrome extension, then watch A and B.** It was down all session, so
   **nothing in A or B has been seen rendering** — and A is exactly the class of defect a
   green suite cannot see. Demo data is seeded and waiting: recruiter
   `slice1-check@example.com` / `slice1-check-pw`, one job with three requirements, and two
   completed screenings (`resume_th.pdf` and `resume_en.pdf`, chosen so a wrong document is
   obvious at a glance). Three checks: switch candidates with the Original tab open; click
   two ranked rows fast; open History on two applications.
2. **Commit A as one slice**, then B, then C+D. Nothing is committed yet. `web/AGENTS.md`
   and `web/CLAUDE.md` are untracked and should go in with the first commit — `next dev`
   regenerates them every run otherwise.
3. **Review the canvas** and iterate on it before writing any more screen code.
4. **Then migrate the pages onto the tokens**, one screen per commit, in the slice order
   above. The primitives in `web/components/ui/` are written and still have no callers.

One decision is open and does not block 1-3: **which language leads the public pages.**
Thai-first is the recommendation — `<html lang="th">`, Thai headline with a short English
line beneath, one set of copy. Bilingual behind a `[locale]` segment is more Next.js to
learn and costs roughly one extra large slice plus permanent copy maintenance. Due before
the public-demo slice.

One environment note worth keeping: a `next dev` server left running overnight answered
every request with `Jest worker encountered 2 child process exceptions`, because its
worker children had died while the machine slept. The tell is in
`web/.next/dev/logs/next-development.log`, where the last `Compiling` line sits hours
before the first error — so the edited files had never been compiled and the error was not
about them. `taskkill /PID <pid> /T /F` and restart; no need to clear `.next`.

---

## 2026-08-18 → 08-19 — the auth story is finished

**No milestone was in progress** — M1–M5 are closed and M6 was closed unbuilt — so this
session took the two named leftovers plus the env hygiene that had been carried for two
sessions. **Both are done, so nothing named is outstanding.** Nothing was pushed (your call, as
always); for how much is waiting, run `git rev-list --count origin/main..main` — this
note deliberately does not say, because the number was wrong within minutes each of the
three times it did. The session ran past midnight, hence the two dates.

| # | Commit | What it is |
|---|---|---|
| 1 | Name the retrieval backend in the example env, and say OCR is on here | `.env.example` gains a `RETRIEVAL_BACKEND` section, `CLAUDE.md`'s OCR framing corrected. Plus `.env` back to `LLM_PROVIDER=fake` (not committed — gitignored) |
| 2 | End every session on a password change, not only the caller's own | `Candidate.token_epoch`, migration `0012`, the `epoch` claim, `assert_live`'s new signature, 6 test cases |
| 3 | Record that the epoch landed, and the mutation call that went the other way | Six documents, and a new `RUNBOOK` section run before it was written |
| 4 | Accept the session as a cookie the browser will not show to script | `app/cookies.py`, the cookie settings and their startup guard, the CSRF check, `tests/test_cookie_auth.py`. **No change to `web/`** |
| 5 | Stop the browser from holding a token at all | `lib/auth.ts` rewritten onto an identity marker, `credentials: "include"`, ~30 `api.*` signatures, 5 pages, `AuthPanel` |
| 6 | Close the auth story, and record the three lessons it cost | These docs, plus `HANDOFF.md` §10 gaining two new instrument entries |

Gates: `pytest -q` **651 → 680**, vitest **137 → 165**, `ruff`/`mypy` (58 files)/
`typecheck`/`lint`/`build` clean. Migration `0012` round-trips on both dialects.
**Zero Gemini quota spent** across the whole session.

### The httpOnly cookie half, in short

Deferred five times, and the owner's decision is what unblocked it: **bearer auth stays
alongside**, so every `curl` in the runbook is untouched. That let it land as two
commits — the server issuing and accepting cookies with `web/` unchanged, then the
browser stopping holding a token — the first of which is independently verifiable.

**The mechanism was measured first, in twenty minutes, before the client half existed.**
CORS needed no change; `Secure` works on `http://localhost`; a cookie set by `:8000` is
stored and returned by a page on `:3000`. And the one that mattered: **it is not, from
`127.0.0.1:3000`.** Cookies ignore ports, so that is a different *site*; both origins are
in `CORS_ORIGINS`, so the request succeeds and only the credential goes missing —
**sign-in 200, everything after it 401**. The client now checks `GET /auth/me` right
after signing in and names that cause instead of looking broken.

### The three things worth carrying

- **When one mechanism can produce the other's symptom, testing the symptom tests
  neither.** Two mutations survived the first draft of `test_cookie_auth.py`: clearing
  the refresh cookie on the wrong `path`, and ignoring the refresh cookie during logout.
  Logout revokes the token *and* asks the browser to forget it, and each masks the
  other's absence. Pinned apart now — revocation by replaying the kept token in a body,
  clearing by looking in the jar.
- **"No test fails when I delete it" separates dead code from *untested* code only if
  you ask what the line is for.** Mutation said the `PASSWORD_CHANGED` revocation was
  redundant once the epoch existed, and this repo's precedent says such a line goes —
  the `is_revoked` fast path and `geometry.py`'s separator reset were both deleted on
  exactly that evidence. It was **kept**: those were *guards*, this is a *record*, and
  bumping an integer writes no history, so deleting it would make a password change the
  one revocation an operator can see no reason for. A test pins it now.
- **The browser found a defect no gate could, for the fourth slice running.**
  `DocumentViewer` fires two *independent* `authorized` calls, so an expired access
  token yields two 401s and two renewals — and a refresh token is single-use, so the
  second presents one just revoked and signs the user out moments after a renewal that
  worked. Driven against a one-minute access token both answered 200, because the first
  response updated the cookie jar before the second request left. **Timing, not a
  guarantee.** Concurrent renewals share one request now.

### Three instruments lied, and none of it reached a report

Worth listing because two are a new species — a *probe* differing from the thing it
stands in for:

- A throwaway API container run beside the stack had **no uploads volume**, so
  `GET /resumes/{id}/file` answered 404 while `/geometry` answered 200. That is
  indistinguishable from a broken auth path.
- The same container took the compose **default `JWT_SECRET`** while the real stack takes
  `.env`'s, so restoring the real API silently killed the browser's session mid-walk.
- And `psql` showed a sign-out revoking the refresh token and **not** the access token,
  which reads as a route ending half a session. It is `purge_expired` doing its job two
  hours later: access tokens live thirty minutes and the sweep runs hourly. A `curl`
  logout moments afterwards wrote both rows. **`revoked_tokens` is sized by outstanding
  sessions, not by history** — it cannot be read as an audit log after the fact.

### The thing worth remembering

**"No test fails when I delete it" separates dead code from *untested* code only if you
ask what the line is for.** Mutation-testing said the `PASSWORD_CHANGED` revocation in
`change_password` was redundant — all 656 cases passed without it, because the epoch
refuses the token first. This repo's own precedent says such a line goes: the
`is_revoked` fast path in front of the SAVEPOINT and the separator reset in
`geometry.py` were both deleted on exactly that evidence.

It was **kept**, and the difference is what it is *for*. Those two were **guards** —
lines whose job was correctness, which something else was already achieving. This one is
a **record**. Bumping an integer writes no history at all, so deleting it would make a
password change the one revocation an operator can see no reason for, and no test would
ever have noticed. So a test was written to pin it instead. A line kept for a reason no
test states is a line the next person deletes.

### Why an epoch and not a session registry

Both were named in `token_service.py`'s docstring as the honest fixes, and the cost
decided it. A registry writes a row on every login, keeps one per live session, and needs
its own sweep — all to answer a question a counter answers without storing anything,
because **ending a generation does not require knowing its members**. The registry is the
right shape only when somebody wants to *list* a person's sessions or end one
individually, and nothing here asks for that.

Three decisions inside it, each confirmed load-bearing by mutation (2, 4 and 3 cases):

- **`assert_live` takes the account row as a required argument.** The standing rule is
  that `decode_token` and `assert_live` are called together; a third paired call would be
  the one somebody forgets. Making the row a parameter turns the invariant into a mypy
  error — you cannot check a token without having looked up whose it is — and it costs
  nothing, because every caller needed the row anyway.
- **A missing `epoch` claim reads as zero**, matching the backfill, so tokens already in
  browsers kept working. Same instinct as `0011`, where the `jti` had been there since
  M1. They still die on the first password change, so it is not a hole.
- **`!=`, not `<`.** A token claiming an epoch the account never reached is forged;
  accepting it for looking newer would make the check a lower bound to overshoot.

### Watched, not only tested

- **Two devices, real Postgres**: password changed on one → the other's access token
  **401** *and* its refresh token **401**. The second is the half that matters — a
  refresh token could otherwise mint access tokens for another fortnight.
- **Signed out is not locked out**: the same account signs in again with the new password
  and gets a working pair. Worth its own check, because "everything is refused" is what a
  too-eager comparison produces and it is invisible from the other test's angle.
- **Both browser tabs fell back and neither reloaded.** A *third* session outside the
  browser changed the password; tab B's next authenticated read went 401 → renewal 401 →
  `clearSession`, and both tabs showed the sign-in form with `navigations: 1` each. The
  epoch and August 16th's `useSyncExternalStore` store composing.
- Console clean **on an instrument proven to speak first** — the probe pair, because
  `read_console_messages` only starts capturing when first called and its silence is
  otherwise indistinguishable from a clean page. It reported "no messages" on the first
  read of this session, which is exactly the trap.
- **The runbook's new statement was run before it was written down.** `docs/RUNBOOK.md`
  gained a "sign out every session for one account" section — one `UPDATE` on
  `token_epoch` — and both of its caveats were driven: they are signed out but not locked
  out, and it leaves **0** rows in `revoked_tokens`, so it records nothing about itself.

### Advice for the owner

- **Docker was not running** when the session started, despite being reported as open —
  no `docker*` process existed at all. `C:` had 53 GB free, so this was not the
  2026-08-14 disk-full failure where builds succeed and container swaps silently do not.
  Started it from `%LOCALAPPDATA%\Programs\DockerDesktop` — the install is per-user, not
  under `C:\Program Files`, which is worth knowing next time.
- **`.env` said `LLM_PROVIDER=gemini`** while the containers had been serving `fake` since
  a stray `export`. It is `fake` now, as you decided, so the next `up` in a fresh shell no
  longer flips the dev stack onto the 20/day cap. **This whole session spent zero Gemini
  quota.**
- **`POST /auth/logout-everywhere` is three lines on top of what landed** and was
  deliberately not built — nothing asked for the route. Recorded in `PLAN.md` so the cost
  is known if you want it.
- ~~**httpOnly cookies is the one named item left**~~ **Done, later the same session**,
  and the trap this bullet predicted turned out to be real: `127.0.0.1:3000` cannot sign
  in and `localhost:3000` can. Measured before the client half was written, which is what
  kept it from being discovered by a confused user instead.
- **Open the app on `localhost`, not `127.0.0.1`.** It is the same machine and not the
  same *site*, so the session cookie is withheld and sign-in appears to work and then
  does not. The client says so by name now, but it is easier to just use `localhost`.
- **Nothing named is outstanding.** M1–M5 closed, M6 closed unbuilt, and both auth
  leftovers done. The next thing is whatever you decide it is — there is no backlog
  driving it. Two candidates, neither urgent: `POST /auth/logout-everywhere` (three lines
  on the token epoch, not built because nothing asked for the route), and the three
  cosmetic smells that have been "do them when already in the file" since 2026-08-14.
- **Commits are sitting unpushed; `git rev-list --count origin/main..main` says how
  many.** No number here on purpose. A count written at the end of a session is stale by
  the next commit, and this paragraph has been wrong three times for exactly that reason
  — including once *within this session*, when correcting it made it wrong again.

---

## 2026-08-16 — M5 closes, and the mechanism it was scoped with did not work

**M5 is complete.** Slice 5 — production compose and a runbook — is done, and with it the
milestone. Four commits, none pushed (your call, as always).

| # | Commit | What it is |
|---|---|---|
| 1 | Run the stack in production mode, on a mechanism that was measured first | `docker-compose.prod.yml`, `.env.prod.example`, the `.gitignore` line |
| 2 | Write the runbook from commands that were actually run | `docs/RUNBOOK.md` |
| 3 | Commit the Thai walkthrough, brought up to date with M5 closing | `docs/WALKTHROUGH-th.md`, which had been sitting untracked |
| 4 | Close M5, and record what its last slice measured | These docs |

Gates: `pytest -q` **633 passed / 38 skipped**, vitest **120**, `ruff`/`mypy` (55 files)/
`typecheck`/`lint`/`build` clean. **Unchanged, and that was the assertion** — this slice
touches no `api/` or `web/` source, so a moved number would have meant it reached
somewhere it should not have.

### The thing worth remembering

**The mechanism the slice was scoped with does not work**, and it was measured before
anything was built on it rather than after. On Compose v5.3.1:

| Mechanism | Result |
|---|---|
| `env_file:` in an override | **Loses** to a base file's `environment:` key. Only keys *absent* from the base come through |
| `--env-file` / `COMPOSE_ENV_FILES` | **Works** — feeds compose's own `${VAR:-default}` substitution. This is what shipped |
| `ports: !reset []` / `!override` | Both work |
| `ports:` merged untagged | **Appends** — dev *and* prod ports published |

`docker-compose.yml` sets every secret as `environment:`, so the scoped `env_file:` would
have left all of them at their dev defaults **and nothing would have said so** — a stack
that looks deployed and is running the development database password. That is the fifth
consecutive session where a plan named a mechanism nobody had tried, and the first where
the check took four minutes and one `docker compose config`.

### Two things the build found that no document named

- **`migrate` runs under `APP_ENV=prod`**, because `migrations/env.py` imports
  `get_settings()`. So a forgotten `JWT_SECRET` fails at the *first* service, not the
  third — watched doing exactly that, with `api`, `worker` and `web` never starting.
  Driving the failure deliberately was worth more than reading the validator: a guard
  nobody has watched refuse is not a guard.
- **Every building service needs its own image tag.** The base names
  `hirelens-api:local` / `hirelens-web:local`, so a prod build in a second compose project
  overwrites them — and the next dev `up` silently adopts a web bundle built against the
  prod API URL. `:prod` tags now.

And **`.env.prod` was not gitignored**: `.env.*.local` does not match it. A file of
production credentials was committable, found by checking the pattern rather than assuming
the existing lines covered it.

### The rehearsal

Cold start in a separate project (`-p hirelens-prod`, own volumes, ports 8100/3100), so
the dev stack ran throughout and its 23 accounts / 21 resumes were intact afterwards.

- **Ten migrations against an empty database** — the cold-start path nothing had exercised
  since `0001`. `alembic current` → `d0e1f2a3b4c5 (head)`.
- **The three data services publish nothing**, believed only after a positive control:
  dev's Redis answered `+PONG` on `127.0.0.1:6379` — *the same reply that was the
  2026-08-14 security finding* — so the probe was proven before its silence meant
  anything.
- The journey in a browser at :3100 on `LLM_PROVIDER=fake`, **zero Gemini quota**:
  **10/10 verified, 0.0% unverifiable, 1 model call**, Thai citations at exact char
  ranges, the arq worker in its own log, console clean on an instrument proven to speak.
- Erasure: `stored_files_removed: 1`, token then 401, 0 rows across four tables, 0 files
  in the volume.
- `NEXT_PUBLIC_API_BASE` at a different port meant the web image genuinely rebuilt — the
  build-arg trap exercised rather than quoted.

**No defect found this time.** Three of the five M5 slices had one that the gates could
not see; this one did not, and that is the right outcome most of the time. The rule was
never that a browser check always finds something.

### Advice for the owner

- **M6 was reviewed the same day and closed unbuilt** — see the section below. The scope
  review is 4 for 4, and this is the first time its finding ended a milestone instead of
  reshaping one.
- **Something for you to run when convenient**: the containers were serving
  `LLM_PROVIDER=fake` while `.env` says `gemini`, left over from an earlier session's
  `export`. Harmless today and it is why this session cost zero quota — but the next
  `docker compose up -d` in a fresh shell will flip the dev stack onto the real provider
  and its 20/day cap. Decide which you want `.env` to say.
- **`useAuth` and the refresh-token denylist are both done** — see below. **httpOnly
  cookies** is the one named item left, and it is genuinely optional: it answers XSS
  token theft, not revocation, and revocation was the pressing half.
- **Four commits sit unpushed.** `git rev-list --count origin/main..main` says so — derive
  it, do not read it here.
- Two small open items, both one line each, both skipped because nothing was in the file:
  `RETRIEVAL_BACKEND` is in no `.env.example`, and `.env` has `OCR_ENGINE=tesseract` while
  `CLAUDE.md` frames it as off by default.

### M6 was reviewed, and closed unbuilt

The eight commits went up (`7a902da..6e583f3`) and CI run **31904311200** is green on both
jobs with **0 annotations** — checked through the API, not read off the tick. Worth having
done: CI had never run slice 4's `pdfjs-dist` install or its `prebuild` worker-copy hook,
and `web/public/` is gitignored in its entirety, so a clean runner was the only thing that
could tell us. It passed. (A correction to what I said before pushing: CI *had* already
seen slices 2 and 3 — runs `31827797239` and `31859784282`. Only slice 4 was unseen.)

Then M6 got the scope review `CLAUDE.md` asks for, and the answer was **do not build it**.
Four reasons, all from the code rather than from judgement, and they are in `PLAN.md`'s M6
section in full:

- **`pipeline/retrieval.py:21-24` already forbids the comparison M6 is built on.** It says
  a retrieval score and a ranking score "must not be shown as though they were
  comparable". BM25 is a retrieval scorer; M6 proposed to evaluate *ranking* against it.
- **`retrieval.py:165` calls the lexical retriever "BM25's idea without its tuning
  knobs"**, with a real IDF at line 232. The coherent question shrinks to tuned-vs-untuned
  BM25 on nine documents.
- **The embedding half is a paid adapter**, gated by the same hard rule as
  `LLM_PROVIDER=anthropic` — price table plus a recorded live run — not an evaluation.
- **The corpus is nine synthetic resumes** built to exercise the parser, and real ones may
  never enter this repo. Labelling your own documents against your own postings produces a
  number nobody should trust, which is the one thing this project exists to refuse.

**The reason is recorded, not the outcome.** "We ran out of time" and "it cannot be built
honestly as scoped" are different claims, and only one of them is true here.

`README.md` was corrected in the same commit: its metrics table listed "Cost and latency
per document" as a shipped free metric, and cost is structurally `$0.00` — the same stale
claim slice 2 was respecified over, still sitting one file away.

### Then `useAuth`, deferred four times, in one commit

The session is an external store now — `useSyncExternalStore` over `localStorage` instead
of reading it in an effect and calling `setToken`. The last genuine
`react-hooks/set-state-in-effect` suppression is gone, and **lint was proven to speak
before the absence was believed** (a deliberate violation injected, warning observed, file
restored). `Auth` is unchanged, so none of the five consuming pages was touched.

Two things fell out that were not the reason for doing it, and the second is the better
one:

- **Two components on one page now agree about who is signed in.** Each `useAuth()` call
  used to own a private copy of the token. Only `AuthPanel` and its page call it today,
  which is why nobody had met the bug — `DocumentViewer` takes `authorized` as a *prop*
  precisely to avoid it.
- **Tabs stay in step.** The store listens for `storage`, which fires only in the tabs
  that did *not* write. A revoked session used to stay live in every other tab.

That second one is also what proved the container was serving the new bundle: this change
adds no route, so `/openapi.json` proves nothing, and cross-tab sign-out is impossible
with the old code. Watched: tab B signs out, tab A falls back to the sign-in form with its
navigation count still 1 — never reloaded.

**17 vitest cases (120 → 137), five mutations each confirmed load-bearing** — dropping the
`emit` from `writeSession` fails 2, from `clearSession` 1, removing the storage listener 2,
keeping a dead token after a failed renewal 1, leaking the listener on unsubscribe 1.
Every one of those fails *silently* in production, which is why they were worth writing.

**`vitest.config.ts` is new, and the reason is the interesting part.** Every `lib/` module
imports from `@/lib/api`, and until now every one of those was `import type` — erased
before the bundler ever resolves the alias. `auth.ts` imports values, so the suite failed
with *"Cannot find package '@/lib/api'"*. Pointing `auth.ts` at a relative path would have
made the error go away and left the next value-import through `@/` to hit the same wall.
The suite is still DOM-free: `localStorage` and `window` are two hand-written stubs with
four methods between them.

### And the refresh-token denylist, deferred four times

`revoked_tokens` (migration `0011`), `services/token_service.py`, and a cron sweep beside
the reaper. `POST /auth/logout` exists and means something for the first time.

**The two claims it rested on were checked first, and one was already false.**
`security.py:46` has put a `jti` in every token since M1, with a comment saying it exists
"so revocation can be added without reissuing the whole scheme" — so nothing about the
token format changed and tokens already in browsers became revocable. And `README.md`'s
route table described a refresh token as **"single-use"**, which it was not: `/auth/refresh`
issued a fresh pair and left the presented token valid for another fourteen days, so a
stolen one kept working *after* the real user had rotated it. That is the concrete hole
this closes, and it was sitting in the README describing behaviour the code did not have.

**Why a table and not Redis**, decided on evidence rather than taste: the suite runs on
in-memory SQLite with no server, and `docker-compose.yml` runs Redis with `--save ""
--appendonly no` — so a denylist there would **forget every revocation on restart**,
un-revoking silently while the operator believed the session was dead.

**One guard was deleted after surviving mutation.** A `if await is_revoked(...)` fast path
sat in front of the SAVEPOINT, and either guard alone passed every test, because the tests
exercise sequential double-revocation rather than a race. The savepoint is the one that is
*also* correct under concurrency, so keeping the cheaper one would have meant keeping the
one that only works when nothing else is happening. `geometry.py`'s separator reset, in a
new costume.

**A test failed on purpose, which was its job.** `test_tokens_issued_before_the_change_still_work`
pinned the limitation and its docstring said that when revocation landed it should fail and
be replaced with its opposite. It did, and it has been — same device as
`test_columns_should_read_one_after_the_other`.

Gates: `pytest` **633 → 651**, five decisions confirmed load-bearing by mutation (3, 3, 1,
1, 1). Migration `0011` round-trips on SQLite *and* Postgres, `alembic check` clean.
Driven against the containers and real Postgres: logout → both tokens 401; a refresh token
used once → 200 and **replayed → 401**; a password change → the old token 401 and the new
pair working; all four reasons in `psql` as upper-case names; and **0** revocation rows
after `DELETE /auth/me`, which is the cascade rather than the row.

**One instrument lied on the way, and I nearly reported it as a pass.** A SQLite migration
round-trip printed `SQLITE OK` — because that was my own `echo`, on a command that had
actually failed with "unable to open database file". Re-run under `set -e`, it genuinely
passes. Eleventh of its kind here, and the plainest: *a success message you wrote yourself
is not a result.*

**Still not done, and pinned so it stays honest:** a password change cannot sign out the
account's *other* devices, because the denylist stores only dead tokens and never
outstanding ones. `test_a_session_on_another_device_survives_a_password_change` fails the
day somebody fixes it.

---

## 2026-08-15 — the overlay lands, and M5 has one slice left

**M5 slice 4 is done.** A citation now highlights on the original PDF, not only in the
extracted text — which is what slice 3's `page_geometry` was measured for, and the item
parked since M2 #8. Four commits, none pushed (your call, as always).

| # | Commit | What it is |
|---|---|---|
| 1 | Serve the original document, and the boxes drawn on it | `GET /resumes/{id}/file` + `/geometry`, `tests/test_resume_file.py` (19 cases) |
| 2 | Draw each citation on the document it was read from | `lib/overlay.ts` + its tests, `components/{PdfOverlay,DocumentViewer}.tsx`, `pdfjs-dist`, the worker copy script |
| 3 | Paint a span once, however many claims rest on it | The defect the browser found |
| 4 | Close M5 slice 4, and record what watching it found | These docs |

Gates: `pytest -q` **633 passed / 38 skipped** (was 614), vitest **120** (was 98),
`ruff`/`mypy`/`typecheck`/`lint`/`build` clean. **No migration, and no change to any
payload that already existed** — `/jobs/[id]` and `/` both had the resume id already.

### What watching it proved

Driven on `LLM_PROVIDER=fake`, so **zero Gemini quota** — the third slice running to
close that way.

- **The payoff, visible at last.** In `resume_th.pdf` the quote `ชำระเงิน` starts at
  character 180 *inside* an unbroken 31-character run, and the overlay covers **8
  characters** (x 167.03 → 201.28). Per-word boxes — what the plan originally
  specified — would have covered all 31. This is why slice 3 changed shape.
- **The two-column page is the one that could not be faked.** Every box lands in the
  left column, on the words it cites. `document_text` is in *reading* order, which is
  not the PDF's internal order, so a client that searched for the text would put these
  boxes somewhere else and look plausible doing it.
- **A scan says why it is empty**: no boxes, and the caption names OCR as the reason.

### The defect, and the instrument

**The browser found one thing no gate could, again.** Two claims resting on the same
quote — the headline and the seniority both cite chars 11–72 — painted that span's
boxes twice, and stacked translucent rectangles render *darker*, which reads as "this
line is more strongly evidenced". 31 boxes for 10 citations; 26 after `distinctSpans`.
That is three slices in a row where the browser caught something the gates could not,
and all three were about what the screen *says* rather than what the code computes.

**And an instrument lied — the ninth, but a new species.** Checking the canvas with
`getImageData` reported it entirely white on a page that was plainly rendered: pdf.js
v6 paints through an ImageBitmap, so a 2d readback sees nothing. I nearly filed it as a
blank-page bug. **The screenshot was the ground truth, and the more sophisticated check
was the wrong one.** A tenth, milder, the same day: the file route's `nosniff` and
`content-disposition` headers read as `null` in browser JS — the CORS safelist hides
them from script. `curl` showed all four present. Both belong beside §10's list.

### Advice

- **Slice 5 is all that is left of M5** — production compose and a runbook. `PLAN.md`
  carries the measured shape: `!reset`/`!override` (not `profiles:`, which fails to
  load the project at all), the `*api_env` anchor cannot cross files, and
  `NEXT_PUBLIC_API_BASE` is a build arg so a prod URL means rebuilding the web image.
- **`web/public/` exists now** and holds exactly one generated file, pdf.js's worker,
  copied by a `prebuild` hook and gitignored. `web/Dockerfile` copies it. If the worker
  ever 404s in a browser, that hook is the first thing to check.
- Four commits are sitting unpushed. `git rev-list --count origin/main..main` says so.

---

## 2026-08-15 — slices 1, 2 and 3 close, the ports close, four leads become findings

**M5 slice 1 is done.** Both of last session's blockers were gone before the first
command: `C:` had **61 GB** free (it was 114 MB), and the Chrome extension connected.
The stack was already sitting on `LLM_PROVIDER=fake` + `FAKE_MODE=hallucinating`, and
the images had been built at 01:40 — **after** the 01:35 commit — so the containers
served the slice-1 code once they were finally recreated. **Zero Gemini quota spent.**

Eight commits in all — three for slice 1 and the ports, three for slice 2, two for
slice 3 (below). Gates run rather than quoted, at the end of the session: `pytest -q`
**614 passed / 38 skipped**, vitest **98**, `ruff check` / `ruff format --check` / `mypy app` clean (55
files), `npm run typecheck` / `lint` / `build` clean. Plus the two opt-in suites against
real servers: `test_postgres.py` **5 passed**, `test_minio.py` **9 passed**.

| # | Commit | What it is |
|---|---|---|
| 1 | Bind the data services to the loopback interface only | The security finding below. `docker-compose.yml` only |
| 2 | Repair the opt-in Postgres suite, which had rotted unnoticed | Two call sites; the module had been half-broken since 2026-08-12 |
| 3 | Close M5 slice 1, and correct what the remaining slices must do | `PLAN.md` slice 1 ticked and slices 2/3/5 rewritten on confirmed findings; `HANDOFF.md` §1, §9 and §10 refreshed. One commit rather than two because the two halves interleave in the same three files |
| 4 | Record the push and its CI run, now that both exist | The repository-state paragraph, plus the opt-in caveat |
| 5 | Serve the usage and quality figures from rows already written | Slice 2's server half: `schemas/metrics.py`, `services/metrics_service.py`, `GET /metrics/usage`, `tests/test_metrics.py` |
| 6 | Put the usage and quality figures on a screen | Slice 2's other half: `web/lib/metrics.ts` + its tests, `web/app/metrics/` |
| 7 | Measure where each character sits, in the pass that measures the offsets | Slice 3: `pipeline/geometry.py`, `parse.py`/`layout.py` rebasing, migration `0010`, `tests/test_geometry.py` |
| 8 | Close M5 slice 3, and record the two things its plan got wrong | `PLAN.md` slices 3 and 4, `HANDOFF.md` §1 and §9 |

### What watching slice 1 proved

It **worked** — worth saying plainly next to the 2026-08-13 row where the same check
found seven defects. The rule was never "a browser check always finds something", it is
that nothing else tells you either way.

One recruiter account was enough, which the plan did not expect: `screenable`
(`web/app/jobs/[id]/page.tsx:174-190`) merges the account's own uploads with the
applicants', so a recruiter can screen a resume they uploaded and no application journey
is needed to reach a screening. Extraction gave **10/11 verified, 9.1% unverifiable,
2 model calls** and the M1 panel still rendered — the regression the shared-component
refactor owed. Then the new half: **1/2 verified, 50.0% unverifiable**, `Python` **Met**
citing the Thai line, `Kubernetes` "No citable evidence", and
`Excluded — could not be traced to the document (1)` naming `requirements[1] Kubernetes`
with the fabrication struck through.

Two things the browser proved that no test had:

- **The fabricated quote did not manufacture a verdict.** `hallucinating` attaches its
  fabrication to a requirement the document does *not* evidence — the sharper test,
  because there is nothing real beside it to hide behind — and the verdict stayed
  unevidenced.
- **The model-call count is read from the stats, not the row that spells it the same.**
  `psql` shows the screening at `attempts = 1` while its stored stats say `2`, and the
  screen said "2 model calls". Had the component read the row it would have said one and
  nothing would have looked wrong.

The console was clean **on an instrument proven to speak first** — a probe
`console.log`/`console.error` pair, confirmed visible before the absence was believed.
Both throwaway accounts erased: `stored_files_removed: 1`, token then 401, `psql` 0 rows.

### The two things found on the way, neither of them planned

- 🔴 **Redis, Postgres and MinIO were published on every interface**, Redis with no
  password. Fixed first and separately, because it is the state of this machine rather
  than a question about a future deploy: three `127.0.0.1:` prefixes. `api` and `web`
  still publish openly — the browser needs them. Proven by re-running both opt-in suites
  against the new binds, which is what shows a bind is *right* rather than merely
  different.
- **The opt-in Postgres suite had rotted since 2026-08-12.** `ingest_resume` gained a
  required `consent_version` in M4's PDPA slice (`77a22c6`) and the module was never
  updated, so two of its five cases had been failing with a `TypeError` ever since.
  Nothing caught it: `pytest -q` skips the module and CI has no database. `HANDOFF.md`
  §1 asserted "4 passed" throughout — wrong twice over, since there are five cases and
  two failed. **An opt-in suite going quiet shows up as neither a red tick nor a changed
  skip count.** Worth a periodic run of every opt-in module for exactly this reason.

### The four leads are now findings

Last session's audit lost 15 of 33 agents to a session limit, so items 2, 3, 14 and 16
were written down as single-source leads. Each was re-investigated and then handed to an
independent agent told to **refute** it. **All four survived** (8 agents, 0 errors, every
refuter returned `refuted: false`), and three change what their slice has to do.
`PLAN.md` now carries the corrected shapes; the short version:

- **Slice 3 is worse than the note said.** `_assemble` takes `list[str]`
  (`parse.py:395-401`) and never sees a pdfplumber `Page`, so geometry cannot be
  measured there *under any implementation*. Measured: 8 of 11 words carry `\x00`, word
  starts drift up to 11 chars — and two things the audit did not have: **`find()` is
  unsound even with zero NULs** (105 of 120 words in `resume_multipage.pdf` occur more
  than once) and the two-column path reorders (11 offset inversions). The answer is
  pdfplumber's textmap, which aligns chars to boxes by construction rather than by
  search.
- **Slice 5's recorded remedy is out of date.** This machine runs Compose **v5.3.1**,
  where `ports: !reset []` and `!override` both work — so the
  `docker-compose.override.yml` inversion is unnecessary. And `profiles:` is worse than
  "insufficient": with the profile inactive the project **fails to load at all**, because
  every infra service is a `depends_on` target. Two traps nobody had named: the
  `*api_env` anchor cannot cross files, and `NEXT_PUBLIC_API_BASE` is a build arg.
- **Slice 4's gate is confirmed.** `resumes.py:299-306` has two conjuncts and neither
  touches `Application.state`, so `WITHDRAWN` and `REJECTED` still grant read access.
- **Slice 2's admin scope is genuinely unsettled**, not just misnamed. `require_role`
  cannot produce a row predicate — but `jobs.py:222-223` is an existing role-branched
  scope that **narrows** ADMIN. That is an owner decision.

### Slice 2 followed the same day

You decided two things and it was built on them: **ADMIN sees every row**, and the
dashboard is respecified as *usage and quality* rather than cost.

Three commits — the server half, the screen, and the docs. Gates: `pytest` **536 → 556**,
vitest **95 → 98**, `ruff`/`mypy`/`typecheck`/`lint`/`build` clean.

**No migration, and no new table.** The schema was shaped for this in M1, which lifted
`claims_verified`, `claims_dropped` and `hallucination_rate` into real columns
*specifically* so the metrics query would be a `GROUP BY` rather than a JSON walk. Four
years of that docstring finally being cashed in.

Four decisions, each confirmed load-bearing by mutation (1 case fails apiece):

- **A group's cost is unknown unless every call in it is priced.** `SUM` skips nulls, so
  the obvious version reports a partial total as though it were complete. A missing total
  is visibly missing; a partial one is not.
- **The hallucination rate is recomputed from the totals, never averaged** from the
  stored per-profile rates. On the test's data the two formulas differ **25×**.
- **Owner scoping is two arms**, because `llm_call_logs` has no owner column. Drop
  either and half the calls silently report zero.
- **The four buckets partition the rows exactly**, so the unattributable row the audit
  found cannot vanish from every total.

**The browser found one thing no gate could**: the screen read *"1 claims dropped"*. The
sentence was built inline in JSX, where `web/`'s no-DOM vitest cannot reach it — the
exact failure mode `lib/evidence.ts` exists to prevent, repeated one slice later. It is
`droppedNote()` in `lib/metrics.ts` now.

The two rules real data cannot demonstrate were **driven with seeded rows and then
deleted**: an unpriced call turned the headline and its own bucket to `unknown` while the
judging bucket kept its real `$0.0000`, and an unattributed call raised the amber banner
and made the hidden bucket appear. Promoting the account to ADMIN took the totals from
5 calls to 28 and reproduced the `psql` baseline exactly.

**Browser flakiness worth knowing about**: the extension reported a viewport of
2133×1012 while screenshots came back 1568×743, so **coordinate clicks landed in the
wrong place** and `Page.captureScreenshot` timed out twice. Ref-based `find` /
`read_page` / `form_input` were reliable throughout. Prefer refs over coordinates here.
One caveat recorded honestly: `form_input` drove the auth form fine but did **not**
commit the job-authoring form's React state, so that job was seeded through the page's
own authenticated `fetch` instead. The authoring UI itself had been driven by hand an
hour earlier in slice 1, and the screen this slice is about was driven entirely in the
browser.

### Slice 3 followed, and the plan was wrong about it twice

You decided **a recruiter keeps read access after a terminal state** — which unblocks
slice 4 — and said to go straight to slice 3. It is done: `app/pipeline/geometry.py`,
rebased in `parse.py`, stored by migration `0010`. `pytest` **556 -> 614**.

**`PLAN.md` was wrong about this slice in two ways, and both only showed up on contact
with the code** — the same pattern the 2026-08-14 audit found, one layer deeper:

- It said *per-word* boxes. Wrong for Thai, which has no spaces: a whitespace "word" in
  `resume_th.pdf` is the unbroken 31-character run `ดูแลระบบกระทบยอดการชำระเงินด้วย`,
  and the real quote `ชำระเงิน` sits **inside** it. Word boxes would have highlighted
  all 31 characters for a quote covering 8. This is the identical measurement that made
  `retrieval.py` tokenize Thai by n-gram — the repo had already paid for this lesson.
- It said the geometry is written *in `_assemble`*. Impossible: `_assemble` is declared
  over `list[str]`, never receives a `Page`, and is the DOCX path besides.

**The mechanism is the interesting part.** Nothing searches for text. pdfplumber's
textmap emits one `(character, source)` pair per character of the extracted string, so
a char range and its box are produced *together* and cannot disagree. The alternative
was measured wrong three ways — NULs, repeated words, and two-column reordering.

**A page whose textmap does not reproduce its text exactly gets no geometry.** That is a
rendered state, not a failure, and it is the same instinct as `detect_reading_order`
answering `None` and the OCR confidence gate refusing a page: a wrong box is a visual
claim nobody can check.

**One mutation survived, so a line was deleted.** Resetting the open run on a separator
passed all 58 tests when mutated — skipping the separator already breaks contiguity, so
the reset could not fail. It is gone, with the reasoning in a comment.

**The load-bearing property was measured, not asserted:** every fixture parsed with
`HEAD`'s parser and with this one, and `document_text`, page spans, `pages_without_text`
and `pages_from_ocr` came back **byte-identical across all 13 documents**. Then watched
end to end — an upload through the browser extracted to the same 10/11 and 9.1% as
before, and read back out of Postgres the geometry covers **347 of 347** inked
characters, with `ชำระเงิน` resolving to 8 boxes for 8 characters.

**The session limit hit during this walkthrough** and the model-backed browser tool
(`find`) began returning 429. Nothing was reported off it: `read_page`,
`javascript_tool` and `file_upload` need no model call and carried the rest. Worth
knowing which browser tools cost one before the next limit.

### Advice for the owner
- **The check nobody scheduled paid again, twice.** Last session it was the audit; this
  session it was noticing the opt-in suite's number had never been re-read, and noticing
  the ports while looking at something else. Neither was on the plan.
- **Nothing was pushed until slice 1 actually closed**, as you asked — and then all of
  it went at once: **7 commits** (last session's 4 plus this session's 3), re-derived
  with `git rev-list --count` rather than believed from the previous note, which said 3.
  CI run `31825047640` is green on both jobs with **0 annotations**, checked through the
  API rather than read off the tick. Slice 2's three commits followed.
- **Slice 3 is done, and it was the largest remaining piece.** Its recorded shape was
  wrong twice over, and both errors were only visible on contact with the code — which
  is now four sessions running that a plan written about unbuilt work decayed before it
  was built. Keep checking the claims a slice rests on at the moment you build it.
- **Only slices 4 and 5 remain.** Slice 4 is unblocked by your decision and rests
  entirely on slice 3's geometry; slice 5 is the production compose, whose security half
  already shipped. Neither is gated on anything now.

---

## 2026-08-14 — M5 slice 1 is written and cannot be watched

**Two commits, gates green, not pushed, and the slice is NOT done** — the browser
check could not run. Both reasons are environmental and both need the owner.

Before any of it, the five M5 slices were audited against the code rather than against
the plan, because the last two sessions each found a document asserting something false
about unwritten work. It found three more, and one live security problem.

| # | Commit | What it is |
|---|---|---|
| 1 | Give the dropped-claim vocabulary a home the screening side can reach | `web/lib/evidence.ts` + `components/{DroppedClaims,EvidenceStatsBar}.tsx`, `ProfileView` refactored onto them. No behaviour change |
| 2 | Show what a screening dropped, beside the verdicts it kept | The actual slice: `/jobs/[id]` renders `judgment.dropped` + `judgment.stats`. No API change, no migration |

Gates, each run rather than quoted: `pytest -q` **536 passed / 38 skipped** (534 + the
two new screening cases), vitest **69** (62 + 7), `ruff check` / `ruff format --check` /
`mypy app` clean, `npm run typecheck` / `lint` / `build` clean.

### Start here next session

Read this entry, then `HANDOFF.md` §1 and §9, then `PLAN.md`'s M5 section — the slice 1
bullet there now carries what was built and what the audit corrected about it.

1. **Nothing is half-written.** Working tree clean, three commits local, **nothing
   pushed**. Re-derive the push state with `git rev-list --count origin/main..main`
   rather than believing this line — it has been wrong here before.
2. **Check free space on `C:` first.** If it is still full, nothing that rebuilds or
   recreates a container will work, and it will not say so honestly (blocker 1 below).
3. **Then finish slice 1 by watching it.** It is code-complete and unverified, which by
   this project's own rule is not done, and `PLAN.md` has it unticked on purpose. The
   walkthrough is below and costs no Gemini quota.
4. **Then tick `PLAN.md` slice 1 → `[x]`** and refresh `HANDOFF.md` §1 with the result.
5. **Do not start slice 2 as written.** It is specified as a cost dashboard and there is
   no cost to show — item 4 in the table below. That needs the owner, not a decision made
   while coding.
6. If picking up something else instead, **slice 4's file route is the one thing that is
   unblocked** — it has no dependency on slice 3 — but read item 14 first, because it
   turns a read-access gap into raw PII bytes.
7. `m4b.candidate` / `m4b.recruiter` and ~20 older throwaway accounts are still in the dev
   database. Left alone rather than swept unasked, as before. Their passwords are recorded
   nowhere, so a walkthrough needing a login means fresh accounts.

### The two blockers

- **`C:` is 100% full** — 114 MB free of 216 GB. Docker Desktop's containerd flipped its
  metadata store to read-only, so `docker compose up -d` **builds the images and then
  fails to recreate the containers**. The running containers are 9 hours old and serve the
  code from before these commits. The command **exited 0** with the error on its last
  line, which is the seventh instrument to tell a confident lie here — add it to §10's
  list: *a compose build that could not swap the container still reports success.*
- **The Chrome extension is not connected.** Same state as the M4 slice 5 session, which
  is the one that shipped seven defects. Not repeating that: the slice stays open.

Once both are fixed the walkthrough is cheap and spends **zero** Gemini quota:
`export LLM_PROVIDER=fake FAKE_MODE=hallucinating && docker compose up -d --force-recreate api worker web`,
then upload → screen → click the candidate. `fake.py` fabricates on the judging path too,
which is the only way to make the panel non-empty (see the data finding below).

### What the M5 audit found, and what it did not

Six areas verified against the code. **The adversarial pass then died on a session
limit**: 15 of 33 agents failed, so slice 1 and slice 4 carry a challenge round and
**slices 2, 3, 5 and the environment survey do not**. Those are single-source and
unconfirmed — a tool that died on a limit produced no coverage, and its findings are
leads rather than facts.

| # | The claim | The code |
|---|---|---|
| 1 | Slice 1 shows "evidence the system has never shown anyone" | **False.** The extraction half shipped in M1 — `ProfileView.tsx:14-71` has had the stat bar and the dropped panel all along. The unbuilt half was judging's, which is what these commits do |
| 2 | Slice 3 writes geometry "in `_assemble`, the pass that already measures page spans" | **False.** The NUL strip runs *inside* the words — 8 of 11 words in `resume_broken_tounicode.pdf` carry a literal `\x00`, so a naive `find()` locates 3 of them. And NFC is not distributive across a concatenation. `_text_of` has to change too |
| 3 | Slice 5 uses a compose `profiles:` | **False.** `profiles:` cannot strip `ports:` from a service. It wants `docker-compose.override.yml` |
| 4 | Slice 2 is a **cost** dashboard | **There is no cost.** `gemini.py:37-46` maps every model to `FREE_TIER`, so `cost_usd` is `0.0` on all 22 rows — never `NULL`. The slice has to be respecified on tokens and `latency_ms`, or it charts a flat zero. **Raise with the owner before building it** |

Three further leads worth checking before slice 2 (unchallenged, so treat as leads):
`llm_call_logs` has no owner column at all, so "the caller's own rows" is **two** joins
landing on different owners — `resumes.candidate_id` for extraction, `jobs.owner_id` for
judging; the `resume_id`-xor-`screening_id` split is a docstring and not a constraint;
and `require_role` is a 403 route gate that cannot widen a row scope, so using it for
"ADMIN sees everything" would 403 the candidates who own the extraction rows.

### The security finding, for the owner

**Redis is published on `0.0.0.0:6379` with no password.** Verified live rather than
inferred: a raw socket to `127.0.0.1:6379` answered `+PONG` and `CONFIG GET requirepass`
came back empty. `docker-compose.yml:40-42` sets persistence flags only and publishes the
port with no host-IP prefix, so Docker binds every interface — anyone on the same network
can `CONFIG SET`. Postgres and MinIO are published the same way. This is the state of the
dev machine now, not a hypothetical about a future deploy. **Not touched**, because it is
slice 5's and nobody asked: the fix is three `127.0.0.1:` prefixes, and it should go in
before the rest of the profile work.

### The data finding that blocks demonstrating slice 1

**There is not one dropped claim in the dev database** — 20 profiles, every `dropped`
empty, `hallucination_rate` 0.0000 across the board. The view built this session would
pass every gate and render nothing. That is not a defect in it; it is what a guardrail
looks like when the provider behaves. `FAKE_MODE=hallucinating` is how to make it speak,
and proving an *absence* needs a positive control — the same rule §10 already carries for
`read_console_messages`.

### Everything that was found broken, in one table

Four documents, one design assumption, three environment faults and eight code-level
gaps. **Only one was in application code** — the missing test — and the rest are worth
more than a long list implies, because every one of them would have been discovered by
building on top of it instead.

| # | What | Where it came from | State |
|---|---|---|---|
| 1 | **`PLAN.md` slice 1 said the dropped-claims evidence had "never been shown anyone".** The extraction half shipped in M1 and has been on the home page since | A scope review describing unbuilt work without reading the built work beside it | **Fixed** — `PLAN.md` corrected, and the slice narrowed to judging's half, which is what these commits build |
| 2 | **`PLAN.md` slice 3 says geometry is written "in `_assemble`".** It cannot be: `_assemble` strips NUL *after* words are extracted, and 8 of 11 words in `resume_broken_tounicode.pdf` contain a literal `\x00`, so a naive `find()` locates 3 of 11 — on the fixture that exists to pin the NUL strip. NFC is also not distributive across a concatenation | The same habit as #1 — a plausible reading of `parse.py` never checked against it | **Open.** `_text_of` has to change too. Recorded here; `PLAN.md` slice 3 not yet rewritten |
| 3 | **`PLAN.md` slice 5 commits to a compose `profiles:`.** `profiles:` cannot remove a published port from a service, and neither can a plain override merge | Naming a mechanism in a scope review without trying it | **Open.** Wants `docker-compose.override.yml` holding the dev port publishing |
| 4 | **Slice 2 is specified as a *cost* dashboard and there is no cost.** `gemini.py:37-46` maps every model to `FREE_TIER`, so all 22 logged calls stored `cost_usd = 0.0` — not even `NULL`, which is the one behaviour the slice says it must get right | The schema supports cost, the provider does not charge, and nobody joined the two facts | **Open, and needs an owner decision** before any of it is built |
| 5 | 🔴 **Redis published on `0.0.0.0:6379` with no password.** A socket to `127.0.0.1:6379` answered `+PONG`; `CONFIG GET requirepass` was empty. Postgres and MinIO are published the same way | `docker-compose.yml` publishing ports with no host-IP prefix, which binds every interface | **Open, untouched on purpose.** Belongs to slice 5 and should go first — three `127.0.0.1:` prefixes |
| 6 | **`C:` is 100% full (114 MB free).** Docker's containerd metadata store went read-only, so `docker compose up -d --build` **built both images and failed to recreate the containers** — and still **exited 0** | The host, not the project | **Open.** Blocks the walkthrough; the running containers are nine hours stale |
| 7 | **The Chrome extension is not connected**, so slice 1 cannot be watched | Same as the M4 slice 5 session | **Open.** The slice stays unticked because of it |
| 8 | **Zero dropped claims exist in the dev database** — 20 profiles, all clean. Slice 1's view would pass every gate and render nothing | A guardrail with a provider that behaves | **Open**, and it is a walkthrough step rather than a code change: `FAKE_MODE=hallucinating` |
| 9 | **`GET /screenings/{id}` served `dropped` with nothing testing that it did.** It returns the stored `Judgment` as an untyped dict, so nothing could strip it — and nothing would have failed if something had. Extraction's twin has existed since M1 | A route whose payload was true by accident | **Fixed** — two cases in `test_screening.py`, `pytest` 534 → 536 |
| 10 | **`ScreeningDetail.judgment` omitted `stats`** on the client, and `RankedEntry`/`ExcludedEntry` omit the `resume_filename` the server actually serves — the page rebuilds names from a local map with an 8-char-id fallback | Hand-mirrored types drifting from the schemas they mirror | `stats` **fixed**; the filename gap **open** and cosmetic until a screened resume is not in the caller's own list, which is exactly when it shows |
| 11 | **The worker container runs an image sha that no longer exists in the image store.** Content is identical today, so nothing is broken — but the next `docker compose up -d` moves it onto a different image with nobody asking | It was restarted rather than recreated after the 2026-08-13 rebuild | **Open**, harmless now, surprising later |
| 12 | **`OCR_ENGINE=tesseract` is active**, contradicting `CLAUDE.md`'s "off by default" framing, and it resolves differently inside the container (bare name on `PATH`) than on the host (`OCR_COMMAND` at a portable install) | `.env` drifting from the docs that describe it | **Open** — a doc fix, but the two resolution mechanisms are worth knowing before debugging OCR |
| 13 | **`RETRIEVAL_BACKEND` is in no `.env` at all** and silently defaults to `lexical` | Never added when the setting landed | **Open**, harmless, worth a line in `.env.example` |
| 14 | **`_owned_resume`'s widening has no application-state predicate**, so a *withdrawn* or *rejected* application still grants the recruiter read access to the resume. Slice 4 would upgrade that from extracted text to **raw PII bytes** | The widening was written for the live case and terminal states were not considered | **Open, and it gates slice 4.** Decide before the file route ships, not after |
| 15 | **`llm_call_logs.resume_id` xor `screening_id` is a docstring, not a constraint**, and there is no owner column at all — so "the caller's own rows" is two joins landing on different owners (`resumes.candidate_id` vs `jobs.owner_id`) | An invariant documented rather than enforced | **Open**, and it decides slice 2's shape: a row with both null is legal and would vanish from every total |
| 16 | **`require_role` cannot widen a row scope** — it is a 403 route gate, so `PLAN.md`'s "ADMIN sees everything via `require_role`" would 403 the candidates who own the extraction rows | Reaching for the nearest-named mechanism | **Open.** `resumes.py:294` already has the right pattern |
| 17 | **`_assemble` is the DOCX path too** (`parse.py:325`) and is imported and called bare by `test_parse.py` | Not a defect — a constraint on slice 3 | **Open**, and it means any new geometry parameter needs a default meaning "no geometry" |

Items 2, 3, 4, 14, 15 and 16 come from the audit's **unchallenged** half and are **leads,
not findings** — see the caveat above. 1, 5, 9, 10 and 11 were confirmed by a second pass
or by running something.

**Updated 2026-08-15: all of them are findings now.** 4 and 15 were confirmed by querying
Postgres directly; 2, 3, 14 and 16 were each re-investigated and then handed to an
independent agent told to refute the result, and **all four survived**. Item 5 (the open
ports) and item 6 (the full `C:`) are **fixed**. Item 3's prescribed remedy —
`docker-compose.override.yml` — turned out to be the pre-v2.24 answer and is superseded;
see the 2026-08-15 entry.

### Things to watch, and to improve

- **The instrument-lie list in `HANDOFF.md` §10 gains a seventh.** `docker compose up -d
  --build` printed its failure on the last line and **exited 0**. Every earlier entry was
  a tool answering the wrong question or answering nothing; this one answers *the wrong
  question about its own success*. The general form: a command that does two things
  reports on one of them. Ask the container what it holds, always — checking the env vars
  is what caught it, and it took one command.
- **An inline `VAR=x docker compose up` did not reach compose at all** in this session's
  shell. `FAKE_MODE` came back as the compose default and `LLM_PROVIDER` came back from
  `.env`. `export` first, then run, and then **ask the container** — the 2026-08-12 note
  says an override does not survive the next `up`; this adds that it may not survive the
  *first* one.
- **Disk space is now a project risk, not a machine detail.** Docker's failure mode when
  `C:` fills is not "out of space", it is a read-only metadata store that lets builds
  succeed and swaps fail. Check free space before a session that rebuilds anything.
- **An audit whose adversarial pass died is half an audit.** 15 of 33 agents failed on a
  session limit. The findings for slices 2, 3 and 5 have one source each and are written
  down as leads on purpose — this is the same rule `CLAUDE.md` already states about a tool
  that dies on a quota limit producing no coverage.
- **The three cosmetic smells are unchanged** and still not worth a detour: `screenable`
  shadowed inside its own `.map` in `web/app/jobs/[id]/page.tsx`, two `refresh*` callbacks
  where a third would be a smell, and `describeEvent` rendering "The system moved it to
  being screened". Do them when already in the file.
- **`useAuth` still owes its `useSyncExternalStore` rewrite**, carrying the one genuine
  `react-hooks/set-state-in-effect` suppression.
- **The Gemini free tier is 20 requests/day and none were spent this session.** The whole
  slice-1 walkthrough needs **zero** — `FAKE_MODE=hallucinating` produces better data for
  it than a real provider can, because a real provider mostly does not hallucinate.
- **`web/` gained two components and no way to test them**, which is the known untestable
  region. The logic went into `lib/evidence.ts` where vitest can reach it, which is the
  move to keep reaching for before reaching for jsdom.

### Advice for the owner

- **The scope review is 4 for 4 at finding false claims about unshipped work.** M4's found
  four in `HANDOFF` §1, M5's found the geometry claim, and this session's audit found
  three more inside M5's own newly-reviewed scope — written five days ago by the same
  process. The lesson is narrower than "review scope": **a claim about code nobody has
  built yet decays silently, and a scope review is not immune to producing them.** Check
  the claims a plan rests on at the moment you build the slice, not only when you plan it.
- **Two of this session's four blockers were environmental, and both were invisible until
  something was attempted.** "Docker is up, the browser is connected" was worth a
  paragraph of direction last session and it was half true this one — Docker was up and
  could not recreate a container; the browser was open and the extension was not
  connected. **Say what is running, then let the first command verify it.**
- **Slice 2 needs a decision from you before anyone writes it.** There is no cost to put
  on a cost dashboard. The honest versions are: build it on tokens and latency and call it
  what it is, or wait until a paid provider exists. Building the specified version means
  shipping a screen of zeroes that looks like a bug.
- **Redis is open on this machine right now.** It is one line per service and it is not
  worth deferring to the rest of slice 5, but it is your call whether it goes in now or
  with the profile work.
- **The work that pays here keeps being the check nobody scheduled.** This session spent
  more time auditing five slices than writing one, and the audit is what stopped slice 1
  from being built to the wrong shape — the "never shown anyone" framing would have
  produced a second copy of a panel that already existed. Budget for the check.
- **Nothing was pushed.** Three commits sit local, as asked.

---

## 2026-08-13 — next@16, and the codemod's two wrong answers

The oldest item on the list, deferred three times. Three high advisories — four
postcss CVEs and four libvips CVEs through sharp, all transitive through
`next@15.5.23` and none reachable except by the framework major. `npm audit` reports
**0** now. Then **M5 was scoped with the owner** and is no longer a draft.

**Four commits, all pushed, CI green with 0 annotations on both jobs** (run
`31683438474`).

| # | Commit | What it is |
|---|---|---|
| 1 | Correct what the notes claim about the repository state | A doc fix. `NOTES.md` said nine commits were unpushed; they were not |
| 2 | Move to next@16 and close the three high advisories | The upgrade, isolated. Nothing else rides along |
| 3 | Record the upgrade, and what a codemod got wrong | `PLAN.md` / `HANDOFF.md` / this entry |
| 4 | Scope M5 with the owner, and correct what it found | M5 draft → commitments, plus the bbox correction |

Gates, each run rather than quoted: `pytest -q` **534 passed / 38 skipped**
(unchanged — nothing in `api/` was touched, which is the point), vitest **62**,
`ruff check` / `ruff format --check` / `mypy app` clean, `npm run typecheck` / `lint`
/ `build` clean, `npm audit` **0**, container healthy, journey walked in a browser.

### Start here next session

1. Read this entry, then `HANDOFF.md` §1 and §9, then `PLAN.md`'s M5 section.
2. **Nothing is half-done.** Working tree clean. Re-derive the push state with
   `git rev-list --count origin/main..main` rather than reading it here — the
   paragraph that said otherwise was wrong last session and is the first commit of
   this one.
3. **Start M5 slice 1: the dropped-claims audit view.** No API change and no
   migration — that was checked, not assumed. Drive it in a browser inside the slice.
4. `m4b.candidate` / `m4b.recruiter` are still in the dev database with one job and
   one shortlisted application. Left deliberately, again. This session's two
   throwaways (`n16.*`) were erased.

### Everything that was found broken, in one table

**None of it was application code**, and that is worth stating plainly rather than
letting a long list imply otherwise. The browser walkthrough found **zero** defects in
`web/` or `api/` — which is the outcome to expect from a bundler swap and is still not
the same as not having looked. What was broken was two documents and two of a
codemod's choices.

| # | What | Where it came from | Fixed |
|---|---|---|---|
| 1 | **`NOTES.md` said nine commits were unpushed.** They were pushed; `git rev-list --count origin/main..main` answers 0 and CI was green on the tip | Written at the end of a session, true when written, false by the next morning | Commit 1. The instruction to re-derive the count rather than read it stays, and is now right twice running |
| 2 | **The codemod bumped ESLint to 10.8.1**, which `eslint-config-next@16.3.0` cannot run on — its `eslint-plugin-react@^7.37.0` dependency has no ESLint 10 release and dies with `contextOrFilename.getFilename is not a function` | `@next/codemod upgrade latest` taking "latest" literally across the whole devDependency set | Commit 2, pinned to `^9.39.5`. The peer-dependency warning at install time was the entire diagnosis |
| 3 | **The codemod added `export const instant = false`** to `layout.tsx` with a TODO pointing at the Cache Components migration — an opt-out for a feature this project does not enable, and a TODO for work in no milestone | Same codemod, applying a defensive transform unconditionally | Commit 2, reverted |
| 4 | **`eslint-disable-next-line` placed at the top of a multi-line `//` block does nothing.** "Next line" means the next *comment* line. The first attempt looked correct and turned 4 errors into 4 errors **plus** 4 unused-directive warnings | My mistake, caught by re-running lint rather than assuming the edit worked | Commit 2. Reason above, bare directive last |
| 5 | **`PLAN.md` M2 #8 and `HANDOFF.md` §9 claimed the pdf.js overlay was nearly free** — that M2 #6 already extracts the bbox geometry, leaving "an endpoint and a canvas". Nothing persists any geometry at all | Written 2026-08-08 and repeated into three documents. A plausible reading of #6, never checked against the code | Commit 4, both corrected. It turned a frontend afternoon into two slices and a migration |

Two of those five (#1 and #5) are the same failure: **a document asserting something
about the repository that nobody re-derived.** This project already had a standing rule
for the first kind and now has evidence for the second.

### The upgrade was four changes, and the version number was the easy one

| What | Why it was not optional |
|---|---|
| `next.config.ts` loses its `eslint` block | Next 16 removed the option with the `next lint` command. `next build` no longer lints at all, so the "lint is a separate CI step" intent it carried is the default, and stating it is now a config error |
| `eslint.config.mjs` drops `FlatCompat` | `eslint-config-next` v16 exports flat arrays directly. Under ESLint 10 the old `compat.extends(...)` does not warn or degrade — it **throws** `Converting circular structure to JSON` from inside eslintrc's own validator |
| ESLint pinned back to 9 | See below |
| Four `react-hooks/set-state-in-effect` suppressions | A rule v16's config newly turns on |

### The codemod was wrong twice, and both were worth catching

`npx @next/codemod@canary upgrade latest` did the bulk correctly. Two of its choices
were not right for this repo.

**It bumped ESLint to 10.8.1.** `eslint-config-next@16.3.0` depends on
`eslint-plugin-react@^7.37.0`, whose *newest published release* still caps at
`eslint ^9.7`. So lint died with `contextOrFilename.getFilename is not a function` —
ESLint 10 removed the context methods the plugin calls. The whole story was in the
peer-dependency warning npm printed at install time and which is very easy to scroll
past. `eslint-config-next` declares `eslint: ">=9.0.0"`; 9.39.5 is what it can
actually run.

**It added `export const instant = false` to `layout.tsx`** with a TODO pointing at
the Cache Components migration. `cacheComponents` is not enabled in this project, so
the opt-out guards nothing and the TODO points at work that is in no milestone.
Reverted.

It also pinned every version exact. Put back to carets: the lockfile is committed and
both CI and the Dockerfile run `npm ci`, so reproducibility is untouched — while
pinning `next` exactly means the next postcss fix *inside* it waits for a human to
notice, which is the failure this whole commit exists to end.

### The new lint rule, and why nothing was refactored to satisfy it

`react-hooks/set-state-in-effect` flags four sites. **Three are false positives**:
`load` is async and every `setState` in it runs after an `await`, so nothing is set
synchronously in the effect body — the rule's analysis does not follow the await
boundary. **The fourth, in `useAuth`, is real**: `localStorage` does not exist during
SSR, so the session is hydrated on mount and `ready` is the flag every page waits on.

Each is suppressed at its own site with its own reason rather than the rule being
switched off, so it still guards new code. `useSyncExternalStore` is the proper fix
for `useAuth`, it changes the hook every route depends on, and it therefore gets its
own commit and its own browser check instead of riding along on a version bump.

One mechanical trap worth knowing: **`// eslint-disable-next-line` in a multi-line
`//` block applies to the next *comment* line, not to the code.** The first attempt
looked right, changed nothing, and turned 4 errors into 4 errors plus 4
unused-directive warnings. Put the reason above and the bare directive last.

### The check that mattered: Turbopack × `output: "standalone"`

Turbopack is the default builder in 16, and there is a known regression dropping
packages from `.next/standalone/node_modules` (vercel/next.js#88844). `web/Dockerfile`
copies exactly that directory and ships **no `node_modules` of its own**, so a green
`next build` proves nothing about the image — which is the same shape as last
session's lesson one layer down.

So it was checked by assembling the image layout by hand before touching Docker:
standalone still emits `server.js`, `package.json` and a `node_modules` carrying
next/react/sharp; `.next/static` is still a separate copy the Dockerfile has to
supply; the booted server answers 200 on `/`, `/jobs` and `/applications`; and the
Tailwind chunk serves 31 KB with its reset intact. `web/Dockerfile` needed **no
change** — but that was a finding, not an assumption.

### Watched in a browser, inside the slice

The rule the previous session bought, applied. Fresh throwaway accounts against the
rebuilt container and live Gemini, **2 model calls**:

- A recruiter registers *as a recruiter* and authors a job leaving both weights at
  the default `1` — the two defects that used to make this impossible.
- A candidate uploads `resume_th.pdf`: consent **unticked on load** with the file
  picker disabled until it is ticked, then `10/10 claims verified, 0.0%
  unverifiable, 1 model call`, and the document pane highlighting each citation —
  emerald for exact, amber for the ambiguous `Python` and `PostgreSQL`.
- The SSE path works: `GET /resumes/{id}/events` served 200 in the API log, so
  `waitForProfile`'s `fetch` + `ReadableStream` survives the bundler change. It is
  the most bundler-sensitive code in the client and the reason a fresh upload was
  worth 1 call rather than reusing old data.
- The applicants panel refreshes itself, sampled every 400 ms with **nothing
  reloaded**: `t=0.0s` Shortlist disabled "Screen this candidate first…" → `t=0.4s`
  "A screening is running." → `t=5.3s` **enabled**. That is last session's seventh
  fix — the one that ships with no unit test *on purpose* and whose only check is the
  browser — still working.
- Both requirements **Met**, 100.0%, 2/2. The Thai requirement matched the resume's
  own differently-worded `ดูแลระบบกระทบยอดการชำระเงินด้วย Python และ PostgreSQL` at
  chars 161–214, and clicking that citation put the ring on exactly that span.
- Shortlisting works and the disabled button then reads **"Already shortlisted."**
- `psql`: the four-row log with `#0 → APPLIED` by `CANDIDATE` **with** `actor_id`,
  `#1`/`#2` by (system) with `actor_id` null and a screening attached, `#3 →
  SHORTLISTED` by `RECRUITER` with both. The Thai label reads back at **36 characters
  / 90 bytes**, typed through the browser. Exactly two `llm_call_logs` rows —
  `extract-v1` on the resume, `judge-v1` on the screening, neither crossed.
- **Zero console output**, and the instrument was proven before the zero was believed
  — `read_console_messages` only starts capturing when first called, so a probe
  `console.log`/`console.error` pair was emitted and confirmed visible first. Without
  that, "no errors" and "not listening" look identical.
- Both throwaway accounts erased with `DELETE /auth/me`: `stored_files_removed: 1`
  and `0`, tokens then 401, `psql` reports 0 rows and 0 jobs left behind.

### Driving this UI from the browser tools — what worked, again

Last session's note paid for itself immediately, so it is repeated rather than
pointed at. **`form_input` sets the DOM value but does not reliably reach React
state**, and coordinate clicks land wrong (the screenshot is 1568 px wide while the
viewport reports more). What worked every time: `javascript_tool` with `el.click()`
and the React-native value setter plus an `input` event.

New this session, and the same class of trap: **`read_console_messages` only starts
capturing when it is first called.** A page that loaded before that returns "no
messages", which is indistinguishable from a clean page. A probe
`console.log`/`console.error` pair was emitted and confirmed visible *before* the
zero was believed. Without that step the headline "zero console errors" would have
been an instrument reporting its own silence — the sixth instrument lie on this
project, caught before it lied.

One harmless red herring: the codemod prints `WARNING: Git directory is not clean.
Forcibly continuing.` even on a clean tree. It means its own scratch state.

### M5 is scoped, and the review paid for itself in its first hour

Third scope review, third time it earned its keep. The draft's entire recruiter-UI
scope was one line — "job list, candidate list per job, requirement-level match
breakdown with citation highlighting, dropped-claims audit view" — and **three of
those four shipped in M3 slice 5 and M4 slice 5**. What is actually left is three
things, not "a full UI".

Seven decisions, in `PLAN.md` with their reasoning. The organizing idea, confirmed
rather than assumed: **every number on an observability screen is a query over rows
the system already wrote, and can name the rows it came from.** Cite your source,
applied to metrics — the same move as "a verdict is derived from a located quote"
(M3) and "a state is a projection of an event log" (M4), a third time. The sign it is
right rather than a slogan: the schema already fits it, and `models/core.py` has said
so in a docstring since M1 — the counters were lifted out of the profile JSON
*specifically* so the metrics query is a `GROUP BY`.

The five slices: the dropped-claims audit view; the cost and quality dashboard; word
geometry at parse time; the pdf.js overlay on top of it; production compose and a
runbook.

### The claim that was false, and how it was caught

`PLAN.md` M2 #8 and `HANDOFF.md` §9 both said the pdf.js overlay was nearly free —
that M2 #6 "now extracts the bbox geometry it needs, so the remaining work is an
endpoint serving the original file and a pdf.js canvas". It has been written down
that way since 2026-08-08 and repeated in three documents.

**Nothing persists any geometry.** `layout.py` computes bounding boxes to *crop*
columns and discards them inside the same function. `PageSpan` holds
`page_number`/`char_start`/`char_end`; `EvidenceRef` holds
`char_start`/`char_end`/`page`. No row anywhere can say where on a page a character
range sits. And for a two-column document `document_text` is in *reading* order,
which is not the PDF's internal order, so a client cannot re-derive it either.

Doing the matching in pdf.js was considered and refused: the client would have to
reproduce the server's NFC normalization, NUL strip and column reordering, and when
it drifted it would highlight the wrong region — a **visual claim nobody can
verify**, which is the one thing this project exists to refuse. So the geometry gets
measured where the offsets are measured, in `_assemble`, with a migration; the
overlay is two slices, not a frontend afternoon.

It was caught by checking a claim before writing it into a plan, which is the same
habit that produced this session's first commit. Both documents are corrected.

### Still open, in order

1. **M5 slice 1 — the dropped-claims audit view.** The guardrail's own evidence, which
   the system has produced on every document since M1 and shown nobody. **No API change
   and no migration**, checked rather than assumed: `ProfileOut.profile` is the stored
   `ExtractedProfile` serialized whole and already carries `dropped`, and
   `GET /screenings/{id}` returns the stored `Judgment` verbatim including `dropped` —
   a route `/jobs/[id]` already calls for `document_text`. `RankedEntry` deliberately
   does not carry it. The rule to hold: this view reports, it never re-asks, and
   nothing on it spends a model call.
2. **M5 slice 2 — the cost and quality dashboard.** A read route over `llm_call_logs`
   and `extracted_profiles`, no migration. Two things it must get right:
   `cost_usd IS NULL` renders as "unknown" and never as 0, and the
   `resume_id`-xor-`screening_id` split is not collapsed — it is what makes "what did
   this document cost" and "what did this screening cost" separately answerable.
3. **M5 slice 3 — word geometry at parse time.** A migration and a change to
   `parse.py`, the most load-bearing module here. The property to pin before anything
   else: every fixture's `document_text` and page spans **byte-identical** before and
   after.
4. **M5 slice 4 — the pdf.js overlay**, on slice 3's geometry.
5. **M5 slice 5 — production compose and a runbook.**
6. **`useAuth` owes a `useSyncExternalStore` rewrite.** It carries the one *genuine*
   `react-hooks/set-state-in-effect` suppression. Its own commit and its own browser
   check, because it is the hook every route depends on.
7. **httpOnly cookies and the refresh-token denylist**, deferred a third time and
   deliberately out of M5. Raise them again if a deploy decision makes them cheap.
8. **M6's evaluation** stays out of the critical path with its one-week timebox.
9. **jsdom** stays out. Revisit only if M5's UI work grows a fourth defect in the
   region `npm test` cannot reach.
10. `m4b.candidate` / `m4b.recruiter` and ~20 older throwaway accounts are still in
    the dev database. Left alone rather than swept unasked.

### Things to watch, and to improve

- **`tsconfig.json` and `next-env.d.ts` are generated now.** `next build` rewrites
  them — `jsx: react-jsx` is mandatory in 16 and `next dev` emits types under
  `.next/dev`. Do not hand-format them; the build will undo it and leave a dirty tree.
- **`next dev` in 16 writes a managed block into `AGENTS.md`.** It has not appeared
  here because only `next build` has been run. The first person to run `next dev` gets
  an untracked file `.gitignore` does not cover — decide then whether to commit or
  ignore it, rather than being surprised.
- **The lint suppressions are load-bearing documentation.** Four sites carry
  `react-hooks/set-state-in-effect` disables with their reasons. Three say "false
  positive, the setState is after an `await`"; if a future refactor makes one of them
  synchronous, the comment becomes a lie and the rule stops protecting anything.
- **`web/` still has the untestable region** — JSX attributes, component effects, and
  the `RequestInit` a call builds. Two of the three ways in were closed by moving logic
  out (`lib/requirements.ts`, the JSON-write table in `lib/api.test.ts`). Keep reaching
  for that before reaching for jsdom.
- **Three cosmetic smells, unchanged and still not worth a detour**: `screenable` is
  shadowed inside its own `.map` in `web/app/jobs/[id]/page.tsx`, two `refresh*`
  callbacks exist where a third would be a smell, and `describeEvent` renders "The
  system moved it to being screened". Do them when already in the file.
- **The Gemini free tier is 20 requests/day.** A full browser journey costs 2. Re-walking
  with data already in the database costs 0 — but the `m4b.*` passwords are recorded
  nowhere, so a walkthrough that needs a login means fresh accounts and 2 calls.

### Advice for the owner

- **A tool that automates a migration still has opinions, and two of them were wrong
  here.** Both were recoverable in minutes and both would have shipped silently: an
  ESLint major its own config cannot run on, and an opt-out for a feature this project
  does not enable. Read a codemod's diff the way you would read a colleague's.
- **The peer-dependency warning was the entire answer**, printed before anything broke,
  in the wall of text after `npm install`. The standing rule here is "read a green run's
  annotations, not just its tick" — same shape, different tool. Add: *read the noise a
  successful command prints.*
- **The scope review keeps finding that the docs are optimistic about work not yet
  done.** M4's found four false statements in HANDOFF §1; M5's found a two-slice parser
  change described as an endpoint and a canvas, believed for five days across three
  files. A claim about *shipped* code gets corrected the first time somebody reads the
  code. A claim about *unshipped* code can sit for months, because nobody has had a
  reason to look. **Those are the ones to check before planning against them** — and
  the cheapest moment to check is the scope review, which is now 3 for 3.
- **Two of the four drafted recruiter-UI items were already built.** Review before
  estimating, not after.
- **The browser check cost 2 model calls and twenty minutes and found nothing.** That
  is the right outcome most of the time, and it is still the only instrument that
  covers what a bundler swap can break: whether the stylesheet loaded, whether SSE
  still streams, whether a citation still lands on the right characters. A check that
  only pays off occasionally is not the same as a check that is not worth running.
- **Say what is running at the start of a session.** "Docker is up, the browser is
  connected" decided the shape of this session in one line, exactly as the previous
  entry predicted it would. It is worth more than a paragraph of direction.
- **Nothing is pushed without being asked** — asked and answered again this session.
  Keep asking.

---

## 2026-08-13 — the browser check finally ran, and M4 slice 5 did not work

The one M4 check that never ran was watching the application journey render. The
Chrome extension connected for the first time this session. Twenty minutes, as
predicted — and it found **seven defects, four of them blocking**, in a slice where
`pytest -q`, `mypy`, `npm run typecheck`, `lint`, `build` and 43 vitest cases were all
green, and where every call each screen makes had been verified against live Gemini.

Suite **529 → 534**, vitest **43 → 62**, **eight** commits, none pushed. All seven are
fixed and re-watched.

### Start here next session

1. Read this entry, then `HANDOFF.md` §1 and §9, then `PLAN.md`.
2. **Nothing is half-done.** Working tree clean, all seven fixes committed with their
   tests, `pytest -q` 534 / vitest 62 / typecheck / lint / container build all green.
   ~~**9 commits sit ahead of `origin/main` and none are pushed** — ask before pushing.~~
   **Corrected 2026-08-13:** those nine were pushed before the session ended.
   `git rev-list --count origin/main..main` answers **0**, `git ls-remote` puts the real
   remote on `c683b3d`, and CI run `31678374829` is green on it. The standing rule that
   produced the original sentence is unchanged — **nothing is pushed without being
   asked** — but this paragraph was reporting a state that no longer existed, which is
   the exact failure the 2026-08-12 entry opens with. Re-derive the count; do not read
   it here.
3. Next two items, in the owner's own order: **`next@16`**, then the **M5 scope
   review**. Neither has been started. §"Still open" below has the detail.
4. The dev database still holds `m4b.candidate` / `m4b.recruiter` from the first
   walkthrough, with one job and one shortlisted application. Left deliberately.

### What was actually broken

Seven defects. The first four made the journey unusable; the last three made it lie or
go stale. Each was fixed as its own commit with a test that fails without it — except
the last, which says in its message why it has none.

| Defect | Why nothing caught it |
|---|---|
| **A candidate could not see any posting.** `GET /jobs` filtered by `owner_id` unconditionally, and a candidate owns none — so `200 []`, and the apply screen that builds its list from it had nothing to offer | The RBAC case registers as a recruiter, authors a job, then *demotes* the account — so the reader owns the row — and asserts the **status code**. `200` was true the whole time and useless |
| **`Create job` would not submit.** The weight input had `min=0.1 step=0.5` while every new requirement starts at `weight: 1`, and a browser needs `(value - min)` to be a whole multiple of `step`. `(1 - 0.1) / 0.5` is 1.8 | The rule lived in JSX attributes and `npm test` has no DOM. There was nowhere for it to be checked |
| **A recruiter could not screen an applicant.** The picker was built from `GET /resumes`, which returns only the caller's own — zero for a recruiter — so the disabled Shortlist could never unlock | `NOTES.md` **predicted this exactly** on 2026-08-12: "`GET /resumes` … stops being true when M4's RBAC lets a recruiter screen someone else's resume." Slice 3 fixed the ranking-filename half of that sentence and left this half |
| **Every transition answered 422.** `moveApplication` and `applyToJob` hand-built their `RequestInit` instead of using `json()`, so neither sent `Content-Type` and Starlette never parsed the body | The 13 cases covering `lib/applications.ts` pin the **pure logic** — which moves to offer, how the log reads — and nothing exercised the wiring beneath them |
| **The ranking showed a UUID prefix, not the filename.** `resume_filename` was already on the wire and the client was still joining it against a list it did not have | Nothing renders in `npm test`, and the API test asserted the field was *present*, not that anything used it |
| **Registration could not choose a role.** `SelfServiceRole` had been a registration field on the server since M4 slice 2 — the only way to become a recruiter — and `api.register` sent `{email, password}`. So a browser could create nothing but candidates, and every recruiter screen was unreachable without `curl` | No test asserted the *body* of a write, only its effect. The server's own tests posted the role directly and passed |
| **The blocked-Shortlist sentence was wrong once shortlisted.** One message for everything-but-`screened` meant an already-screened, already-shortlisted application was told "Screen this candidate first" | The test asserted the button was *blocked with a reason*, not which reason. A disabled button exists to teach the rule, so teaching the wrong one is worse than none |
| **The applicants panel never refreshed.** `applications` was read once on mount; the poll after a screening re-read only the screenings, so the panel and the panel below it showed two versions of one fact until a reload | A component effect, and `web/` has vitest with **no DOM** by design. There is nowhere for it to be checked — see "the fix that ships without a test" below |

### The shape they share

**Every one of the four is wiring, and the server was right in all four cases.**
`POST /jobs/{id}/screenings` answered 202 for an applicant's resume the whole time;
the transition route worked the moment a header was added; `resume_filename` was
already being served and the client was still joining it client-side.

That is what makes this session's lesson narrower than "test more". The Python suite
is thorough, `lib/applications.ts` is genuinely well tested, and neither could see any
of this, because **the bugs live in the seam between two things that are each correct.**
A test of pure logic cannot reach it and a test of the API cannot either.

### The test that could not fail, in its fifth costume

`test_a_candidate_may_still_read_a_job` is the clearest one yet. It reads:

```
register as recruiter → author a job → demote to candidate → assert GET /jobs is 200
```

Every line is deliberate and the assertion is about the **status code**. So it passed
against an implementation that returns `200 []` to every candidate who ever lives. The
replacement asserts the *contents*, with two accounts — which is slice 3's
`actor_role`-not-`actor_id` lesson again, and the fifth session running that the fixture
rather than the code was the thing that was wrong.

### One design call, taken with the owner rather than silently

Opening `GET /jobs` broke `test_someone_elses_job_is_404_even_for_a_recruiter`, which
was written on purpose with its reasoning attached. Two coherent answers existed and
one of them (candidates yes, peer recruiters no) meant letting a **role** gate a **row**,
which is the thing M4 says never to do. So it went to the owner rather than being
decided in passing.

**A posting is public to read.** It is an advertisement, and once `GET /jobs` hands
every posting's id to every candidate, a 404 on the detail route hides nothing. The old
test now pins the boundary that actually matters — every *write* is still 404, and so is
everything the posting produced: a ranking, a screening, an applicant list all carry
verdicts about named people and stay on `_owned_job`.

### Verified by using it, not only by fixing it

The whole journey re-walked in a browser afterwards with **no `curl` anywhere**: a
recruiter authors a job leaving both weights at the default, a candidate uploads
`resume_th.pdf` with consent (10/10 verified, 1 model call), sees the posting, applies;
the recruiter screens that applicant from their own panel — 100.0%, 2/2 met including
the Thai requirement — and shortlists. `psql` afterwards shows the log with the
attribution intact: the two system moves anonymous with a screening attached, the two
human moves carrying `actor_id`. The Thai label reads back at 36 characters / 90 bytes,
typed through the browser rather than through a shell.

Consent was watched too, and it is right: unticked on load, with the file picker
disabled until it is ticked. Both throwaway accounts were erased through
`DELETE /auth/me` — `stored_files_removed: 1`, token then 401, 0 rows in `psql`.

### The other three, and a walkthrough that watched the clock

The remaining three were fixed the same day and the journey walked a **third** time on
the rebuilt container. The interesting one is the applicants panel. With the panel
sampled every 400 ms and nothing reloaded:

```
t= 0.0s  APPLIED (1)         Shortlist disabled — "Screen this candidate first…"
t= 0.4s  BEING SCREENED (1)  Shortlist disabled — "A screening is running."
t=20.5s  SCREENED (1)        Shortlist enabled
```

Three renders that were previously one frozen render plus a reload. The middle line is
the second fix showing up in the same trace — before it, that state said "Screen this
candidate first" about a screening that was already running.

### The fix that ships without a test, on purpose

The panel fix has **no unit test**, and that was a decision rather than an oversight.
`web/` has vitest with no DOM and no React testing library — the same property the
Python suite protects by needing no server — and the bug lives in a component effect.
Two tests were available and both were refused:

- An `applicationsFollow(applications, screenings)` invariant would have to know when
  the system's move is *refused* (terminal, or `shortlisted` + `completed`), which
  means re-implementing the server's `_ALLOWED` table on the client. That is precisely
  what `lib/applications.ts` says never to do: "a second place for them to be wrong,
  and the client's copy would be the one nobody notices drifting."
- Asserting the refresh set is `[screenings, ranking, applications]` restates the line
  above it and fails only when somebody edits both together. A tautology.

So the commit says there is no test and names the browser as the check. **A decorative
test is worse than an honest gap** — it is the "test that could not fail" in yet another
costume, and this session has now met five of those.

### The standing rule this session bought

Written into `CLAUDE.md` ("How to work here" #7) and worth repeating: a five-agent
background audit died on a session limit and returned `{"confirmed": []}` — an empty
result from a run that never happened, which looks exactly like a clean bill of health.
At that moment two finished, fully green fixes were sitting uncommitted with nothing on
disk explaining them. Hence: **commit each finished piece the moment its gates are
green**, and treat a tool that died on a quota limit as having produced no coverage.

### Things to watch, and to improve

- **`web/` has one untestable region, and it is now load-bearing.** Four of the seven
  defects and the whole of the seventh live in code `npm test` cannot reach: JSX
  attributes, component effects, and the `RequestInit` a call builds. Two of the three
  were closed by moving the logic *out* — `lib/requirements.ts` for the weight bounds,
  a table over every JSON write in `lib/api.test.ts`. That is the pattern to keep
  reaching for. The one left is the panel refresh, and if a fourth of these appears it
  is probably time to talk about jsdom rather than keep paying the browser tax.
- **Driving this UI from the browser tools has one real trap.** `form_input` sets the
  DOM value but does **not** always reach React's state — the consent checkbox looked
  ticked and the upload still went out with `consent=false` (the server correctly
  refused it, which is slice 4 working). Coordinate clicks were also unreliable here:
  the screenshot is 1568 px wide while the viewport reports 2133, and clicks landed
  somewhere else. What worked every time was `javascript_tool` calling `el.click()`,
  and the React-native value setter plus an `input` event for text fields. Use that.
- **`describeEvent` reads slightly oddly for one state.** The timeline says "The system
  moved it to **being screened**" because `STATE_LABELS.screening` is "Being screened"
  and the sentence lowercases it. Not wrong, not a defect, but if anyone touches that
  file it is worth a nicer phrasing.
- **`page.tsx` shadows `screenable`**: the memo of screenable resumes, and a
  per-row boolean inside its own `.map`. ESLint is happy and it reads badly.
- **Two `refresh*` callbacks now exist** — `refreshAfterEdit` (job, screenings,
  ranking) and `refreshAfterScreening` (screenings, ranking, applications). They are
  genuinely different sets, but a third one is a smell; if one appears, model "what
  this action moves" properly instead.

### Still open, in order

1. `next@16` for the 3 high advisories. Deferred *again* this session, deliberately —
   the browser check outranked it. All four route files are `"use client"` and
   `/jobs/[id]` uses `useParams()`, so the async-`params` migration does not apply.
   `output: "standalone"` is load-bearing for `web/Dockerfile`, so check the standalone
   build still emits what the Dockerfile copies before rebuilding the container — and
   then re-walk the journey against it, which is now cheap because the acceptance test
   is written down two sections above.
2. **M5's scope is still a draft.** Its review is now worth more than it was: roughly
   two of the four "full recruiter UI" items are already shipped, so the UI half of M5
   is about **two** items (the dropped-claims audit view, and the parked pdf.js
   overlay), not "a full UI". Six questions to bring, each with a recommendation
   rather than a blank slate: what is actually left of the recruiter UI; whether the
   pdf.js overlay justifies a route serving **raw PII bytes** (and note an OCR'd page
   has no bbox geometry to overlay onto at all); observability as an in-app dashboard
   over `llm_call_logs` (bounded, no new infrastructure) versus shipping logs
   somewhere (breaks "every dependency has a no-server default" unless it goes behind
   a seam); httpOnly cookies now or later (they drag in the twice-deferred
   refresh-token denylist, but would make `EventSource` viable again — a
   simplification as well as a hardening); what "deploy" means; and M5's organizing
   idea. The proposal for the last one, to confirm rather than assume: **every number
   on an observability screen is a query over rows the system already wrote, and can
   name the rows it came from.** Cite your source, applied to metrics.
3. M6's evaluation stays out of the critical path.
4. Two throwaway accounts from the *first* walkthrough (`m4b.candidate`,
   `m4b.recruiter`) are still in the dev database with one job and one shortlisted
   application between them. This session's two (`m4c.*`) were erased; those were
   left alone rather than deleted unasked.

### Advice for the owner

- **A slice is not done when its calls are verified; it is done when somebody uses it.**
  This one was signed off with "every call each screen makes was exercised" — true, and
  it did not notice that a candidate could not see a single job. Put the walkthrough
  *inside* the slice. M3's slice 5 did exactly that and shipped clean; M4's slice 5
  deferred it and shipped four blocking bugs.
- **The warning in the handoff was worth writing and worth acting on.** Last session
  recorded the gap honestly instead of glossing it, and named it the first thing to do.
  That paragraph is the entire reason these were found before anyone else met them.
- **When a green test guards a feature nobody has used, ask what it asserts.** Three of
  this session's four blocking defects had a test sitting next to them that passed for a
  reason unrelated to the behaviour anyone wanted.
- **"No test, and here is why" is an acceptable commit — a decorative test is not.**
  The seventh fix ships without one because the only two available would either fork
  the server's rules onto the client or restate the line above them. Both would have
  read as coverage in a review and defended nothing. The gap is written into the
  commit message so the next person can close it properly if the harness ever grows a
  DOM.

### How to run a session on this project

Written down because the same four things have paid off repeatedly, and because a new
session starts cold.

- **Open with what is running, not just what to build.** "Docker is up, the browser is
  connected" changed what was worth doing this session more than any instruction did —
  the browser check had been blocked for two sessions and became the cheapest item in
  the project the moment the extension connected. Saying which of Docker, the browser
  and the Gemini key are available is worth more than a paragraph of direction.
- **Expect a design fork to come back as a question, and answer it.** Opening
  `GET /jobs` broke a test that was deliberately written with its reasoning attached.
  Two coherent answers existed and one of them quietly violated M4's own rule, so it
  went to the owner. That is the right shape: a test written on purpose is never
  flipped silently. The answer ("a posting is public to read") took thirty seconds and
  is now pinned by a test of its own.
- **Say when to stop, and the order.** "Fix the four blocking ones first", then "finish
  the remaining three before moving on" both kept a session that could have sprawled
  into `next@16` and M5 on one thread. Ordering beats scoping here.
- **Nothing is pushed without being asked.** Nine commits are sitting on `main` locally.
  That is deliberate and has been confirmed twice; keep asking.
- **A budget worth knowing:** the Gemini free tier is 20 requests/day. A full journey
  costs about 2 (one extraction, one judging). Re-walking with the *same* data costs 0,
  which is why the re-walk after `next@16` is nearly free.
- **And the rule this session bought** (now `CLAUDE.md` #7): finished work gets
  committed the moment its gates are green, and a tool that died on a quota limit
  produced no coverage — its empty result is not a clean result.

---

## 2026-08-12 — M4 is scoped, and closes

Eleven commits. The first fixes documentation that had gone wrong, the second records
the scope review M4 was gated on, and the rest ship all five slices — the visibility
timeout, RBAC, the application state machine, PDPA, and a thin UI for the journey.

Suite **439 → 529**, vitest **28 → 43**, four migrations, all pushed and green.

### The docs were lying about the docs

Picking the project up meant reading `HANDOFF.md` first, and four things in §1 were
false — two of them in the paragraph that exists to tell you what to trust:

- the `pytest -q` row said **411**; it is 439, and retrieval's 28 cases were missing
  from the breakdown
- "everything through M3 slice 4 is pushed" and "slice 5 is committed but not yet
  pushed". `git rev-list --count origin/main..main` answers **0**, and CI is green on
  the tip. The sentence right underneath — *check that count rather than trusting this
  paragraph* — was correct, and the paragraph was not. That sentence stays.
- the "the model is never asked for a verdict" paragraph appeared **twice**, the
  second copy left over from mid-M3, and it carried a contradiction with it: one
  paragraph said slice 4 was the only free slice, another said three of six were

The README was still announcing M1. Worth the twenty minutes on its own, but the
sharper point is that **a handoff which is wrong about its own repository state is
worse than no handoff** — every one of those errors would have been believed.

### The four calls, settled before any code

`PLAN.md`'s M4 was a draft reconstructed from the README, and both it and HANDOFF §9
said to review it with the owner first, because that is why M3 went cleanly.

| Question | Decision |
|---|---|
| Is an `Application` a row? | **Yes, a first-class one.** The system has no notion of who applied to what — a screening is `(job × resume)` the job's owner pushes through — so "applied → screened → shortlisted" means nothing until applying does |
| RBAC shape | **A `role` column on `Candidate`**, which is the promise HANDOFF §5 already made |
| PDPA depth | **Delete and export first**, consent as a flag at upload. A retention scheduler is new infrastructure and is out |
| The visibility timeout | **Out of M5, into slice 1** |

And the idea that carries the guardrail into the milestone, which HANDOFF §9 had
asked for by name: **an application's state is never asserted, it is derived from an
append-only log of transitions.** Two rules fall out rather than being bolted on —
you may not shortlist someone who has not been screened, and a rejection carries a
reason.

### Slice 1: the failure that never gets to fail

Everything in the retry policy handles a job that *fails*. A worker that simply stops
— power loss, OOM, `docker kill` — never gets there. The claim is committed, and then
nothing, and every road out was closed: redelivery skips the row, `POST /retry`
answered 409, re-upload deduplicates onto it.

The decision that mattered: **reuse `decide_retry` rather than reset the status.** A
reclaim counts against `failed_attempts`, so a document that kills its worker every
time dead-letters instead of looping reap → requeue → die. **A reaper that resets is
the obvious implementation and it introduces an infinite loop**, silently, on exactly
the documents most likely to trigger it.

The generous 900 s default is the other half of the trade: the claim writes
`last_attempt_at` once and never heartbeats, so the timeout has to cover a whole job.
Reaping a worker that is merely slow is wasteful but safe — the loser's `_claim` sees
`extracted` and skips.

### A test that could not fail, caught by the habit rather than by luck

All 32 tests passed first run, so — the standing habit — each decision was reverted
and the suite re-run:

| Mutation | Cases that fail |
|---|---|
| Reclaim as a plain status reset | **3** |
| A missing `last_attempt_at` is not stalled | **1** |
| No UTC normalisation of a naive timestamp | **7** |
| **Drop the re-check under the lock** | **0** ← |

The last one is the interesting one. "Two sweeps in a row only reclaim once" passed
against a version with **no guard at all** — because the second sweep's *candidate
query* already excludes a row the first moved to `pending`. The guard under the lock
never executed. Green forever, catching nothing.

**The fix was to the code, not the assertion**, which is the third session running
that has been the right answer. Listing candidates and reclaiming one are separate
functions now — which they should always have been, since `_record_failure` commits
and drops the locks the list took — and the test drives `reclaim_resume` directly with
a row that stopped qualifying. Three variants of removing the guard now fail 1, 2 and
3 cases.

### An instrument that would have lied, spotted before it did

SQLite's `DATETIME` storage format **has no timezone field**, so `last_attempt_at`
reads back naive there while `utcnow()` is aware. Comparing them raises `TypeError`
rather than answering wrongly — which is the merciful version — but only because it
was handled at the point of comparison. The suite runs on SQLite and production does
not, so this is the class of thing that ships green and fails on Postgres or the
reverse. A test pins it.

### Verified by killing a worker, not only by tests

Docker came up later in the session, so slice 1 was watched end to end against
Postgres + Redis + the ARQ worker + real Gemini. `api` and `worker` rebuilt first —
and since this slice adds **no route**, `/openapi.json` proves nothing, so the
containers were asked directly what they hold (`cron_jobs` → `cron:reclaim`,
`can_retry` a two-argument predicate).

```
docker compose kill worker   the instant the row read `processing`
psql   PROCESSING | attempts=1 | failed_attempts=0 | failure_reason IS NULL
       can_retry=false     POST /retry -> 409
```

The job never got to fail — that is the whole point of the slice, and it is what the
null `failure_reason` says. Then the timeout boundary, measured rather than assumed by
ageing the claim by hand against a 30 s setting: **29 s → 409, 31 s → 200**, read on
Postgres where `last_attempt_at` is `timestamptz` (the dialect the SQLite naive-datetime
test cannot reach).

And the sweep, in the worker's own log:

```
stalled at processing, reclaiming
attempt 1 failed (WorkerVanished), retrying in 5s
queued as job resume:...:1
reclaimed 1 row(s) stalled beyond 30s: 1 resume(s), 0 screening(s)
```

**Then Gemini went down mid-check, and proved the decision for free.** A 503
UNAVAILABLE on the requeued job meant two more failures at 5 s and 10 s, and the row
**dead-lettered after 3 attempts — of which the reclaim was attempt 1**. That is
exactly what a plain status reset would have lost: it would have looped forever.
Nobody scripted it; the provider obliged. `POST /retry` then reached `extracted` on
attempt 4 once Gemini recovered — 10/10 verified, 0 dropped, 10/10 spans slicing back
out, all tier-1 exact.

The screening half too: created with the worker stopped so it queued without spending
anything, stranded with a 120 s-old claim, then **completed 2/2 met** after the reaper
moved it. `psql` afterwards shows 1 `extract-v1` on the resume and 1 `judge-v1` on the
screening, neither crossed — M3's cost split survives the reaper.

### A fourth instrument lie, and this one looked like a bug in the code

The reaper sat there doing nothing for forty seconds while the row was plainly stale.
The cron was firing and succeeding; `find_stalled`, run by hand inside the API
container, found the row immediately.

The cause: `JOB_VISIBILITY_TIMEOUT_SECONDS=30 docker compose up -d api worker` had set
the timeout, and a later plain `docker compose up -d worker` **recreated the container
and re-resolved `${JOB_VISIBILITY_TIMEOUT_SECONDS:-900}` back to the default.** The
worker was correctly declining to reap a claim 200 seconds into a 900-second timeout.

The 2026-08-08 entry recommends a command-line override precisely because "there is
nothing to restore". The other half of that, learned here: **there is nothing to keep
either**, and a later partial `up` silently reverts it. One `docker compose exec worker
python -c 'print(get_settings()...)'` answered it in seconds — the same move that caught
the stale `page_spans` model in an earlier session.

### Slices 2, 3 and 4, in the same session

RBAC, the application state machine and PDPA all landed after the reaper. Suite
**439 → 529**, vitest **28 → 30**, four migrations, everything pushed and green
(CI `31590471473`, **0 annotations**).

**Slice 2 — a role on the one actor.** The rule worth not losing: a wrong *role* for
a route is **403**, not *your* resource stays **404**. Merging them is a one-line
change with no visible symptom that undoes M3's whole ownership story, so
`test_rbac.py` asserts the codes rather than just that a request was refused.
Migration `0007` backfills `RECRUITER` from `jobs.owner_id` rather than guessing —
and its one wart is written down: a downgrade discards the only record of a role, so
re-running it demotes a recruiter who has not posted anything. Watched on Postgres.

**Slice 3 — an application state you can account for.** `state` is a projection of an
append-only event log, never a fact. Two rules fall out rather than being bolted on:
a shortlist is reachable only from `screened` and records the screening it rests on,
and a rejection carries a reason. `screening`/`screened` are set by the worker from
the `Screening` row; the system never gets an opinion about a person.

**Slice 4 — consent, export, erasure.** Erasure deletes the stored files *before* the
rows and abandons everything if one refuses, because the other order leaves an object
in the bucket that nothing points at — undiscoverable and therefore unerasable, which
is the actual PDPA failure. Export is a subject-access request rather than a dump of
everything you can see: a recruiter may read an applicant's resume and it is still
not theirs to export.

### Four bugs, and three of them were invisible to a green suite

| Found by | What it was |
|---|---|
| Reading a live audit log | **Every recruiter decision was logged as the system's.** `Actor` derived the account id from the mover, and the job owner's id is not on the application. The test asserted `actor_role` — correct — and not `actor_id` |
| A test failing for the wrong reason | **The event log came back shuffled.** SQLite's `CURRENT_TIMESTAMP` has one-second granularity, so a journey taking milliseconds writes every event with the same time and the tiebreak fell through to a *random UUID* |
| A test failing for the wrong reason | **SQLite was ignoring every `ON DELETE` clause.** It does not enforce foreign keys unless asked, so `CASCADE` and `SET NULL` were inert there and live on Postgres — and the whole suite runs on SQLite |
| The suite, immediately | A lazy `job.requirements` in the export — `MissingGreenlet`, M3 slice 1's bug in a fourth costume |

The middle two are the same shape and worth stating together: **a property that is
enforced in production and unenforced in the test environment is worse than one that
is enforced nowhere**, because the suite reports success. That is the NUL-in-SQLite
lesson from §11 with two new faces, and the defence both times was writing the test
that needed the behaviour rather than the test that described the code.

The first one is a different lesson. `actor_role` was set correctly and `actor_id`
was null, so the assertion that existed passed while the log was useless. **Assert
*who*, not what kind.**

### Slice 5, and the check it could not run

The candidate's half (`/applications`) and an applicants panel on `/jobs/[id]`. **No
API change and no migration** — `ApplicationOut` already carried `job_title` and
`resume_filename`, so a list needs no second request per row, which is the same thing
slice 5 of M3 noticed about `GET /jobs/{id}/ranking`. Twice now, the slice that puts a
face on a milestone has been cheap because the earlier slices stored the right things.

The decision worth keeping: **the client offers moves, it does not decide them.** The
rules live in `app/applications.py`, and a second copy in TypeScript would be the one
that drifts without anyone noticing. `availableMoves` mirrors the table; when the two
disagree the server's 409 wins and its sentence — written for a person — is what gets
shown. The corollary is that a move which is not available yet is **disabled with the
reason rather than hidden**: a missing button is indistinguishable from a bug, while
one that says "screen this candidate first, so the decision rests on cited evidence"
teaches the rule.

**And the check that did not happen: nobody has watched it in a browser.** The Chrome
extension was not connected. Every gate is green, and every call each screen makes was
exercised against the containers and live Gemini — the timeline came back reading
exactly what `describeEvent` produces, and the shortlist the UI disables is refused by
the server with the same sentence. That is a good deal of evidence and it is **not the
same** as somebody looking at it, which this project has learned twice. It is written
into `HANDOFF.md` §1 as the first thing to do next session rather than left implied.

One instrument note from trying: fetching `/applications` and grepping the HTML for its
headings found nothing, because the page returns `null` until the client auth hook is
ready. The probe was wrong, not the page — the fifth time this session that the first
answer came from a badly aimed instrument.

### Still open, in order

1. **Watch the journey in a browser.** The one M4 check that did not run.
2. `next@16` for the 3 high advisories. An isolated commit, not tangled into a slice.
3. **M5's scope is still a draft** reconstructed from the README. M3's and M4's scope
   reviews both paid for themselves; do it again.
4. Next 15 → 16 for the postcss and sharp advisories, **now 3 high**. An isolated
   commit, not tangled into a slice.
5. M6's evaluation stays out of the critical path.

### Worth knowing next time

- **`JOB_VISIBILITY_TIMEOUT_SECONDS` is passed through `docker-compose.yml`** and
  documented in `.env.example`. It is the one job setting whose right value is
  deployment-specific — it has to cover the slowest *whole* job, since the claim is
  written once and never heartbeats.
- **`ResumeOut.of` and `ScreeningOut.of` take `Settings` now**, because `can_retry` is
  time-dependent: a stalled `processing` row becomes retryable and the timeout says
  when. Five call sites, all threaded through the existing `SettingsDep`.
- The throwaway account was deleted afterwards (cascading its job and screening away),
  and the worker was put back on `.env`'s 900 s, confirmed by asking the container
  rather than assuming.
- `JobContext` gained a `queue`, under a `TYPE_CHECKING` import. The reaper is the only
  job that puts work *back* on the queue, and `app.queue` imports `app.jobs`.
- arq's `cron()` takes cron fields, not an interval, so the sweep is `second=0` —
  once a minute. An interval knob would have been false precision beside a 900 s
  timeout, and the setting was removed again after being written.

### Advice for the owner

- **Distrust the handoff's claims about the handoff.** Four §1 statements were stale,
  including "slice 5 is not pushed" — and the *instruction to verify that one* was
  sitting directly beneath it, unheeded for two commits. Documentation about
  fast-moving state needs the same treatment as a cached value: re-derive it, or say
  where to.
- **A reaper is the one component whose obvious implementation is a loop.** Reset the
  status and you have built a machine that retries forever on exactly the inputs that
  break workers. It cost one sentence of thought and no extra code to route it through
  the policy that already knew how to give up.
- **The "could this have failed?" pass earned its keep for the fifth session running,
  and this time it found a guard with zero coverage rather than a weak assertion.**
  Worth noticing what the fix was: not a cleverer test, but splitting a function so
  the property had somewhere to be checked. When a test cannot fail, the code usually
  has the wrong seams.
- **The live run is still where the interesting things happen, five slices running.**
  Every gate was green before Docker came up, and the run still produced three things
  no test gave: the measured 29 s/31 s boundary on the dialect that actually runs in
  production, a provider outage that demonstrated the budget guard for free, and a
  forty-second stretch where the code looked broken and the *instrument* was wrong.
  The last one is the fourth of its kind here and the first that impersonated a bug
  rather than a pass. Slice 3 then added a fifth: an audit log that read `by system`
  where a recruiter's name belonged, which no assertion in the suite was looking at.
- **Ask what the test environment cannot enforce.** Two of this session's four bugs
  were properties that Postgres holds and SQLite silently does not — timestamp
  precision and foreign keys — and the suite runs only on SQLite. "It passes locally"
  and "it is correct" diverge exactly there, and the gap is invisible in both
  directions. Worth a standing question before trusting any test of a *database*
  behaviour: would this pass if the behaviour were absent?

---

## 2026-08-12 — retrieval lands, and M3 is closed

Slice 6, the last of the milestone. Screening costs a model call per resume, so
something has to say where to spend it first. `GET /jobs/{id}/candidates` orders the
caller's resumes by term overlap with the job's requirements — **no model call, no new
table, no migration**, like ranking before it.

Suite **411 → 439**.

### The measurement that decided the design

Thai has no spaces between words. That is not a detail to handle later; it is the
whole design, and it was measured before a line was written:

```
resume_th.pdf — longest unbroken Thai run: 31 chars
    ดูแลระบบกระทบยอดการชำระเงินด้วย
    'ชำระเงิน'   whitespace-token=False   substring=True
    'วิศวกรรม'   whitespace-token=False   substring=True
    'ทักษะ'      whitespace-token=True    substring=True
```

Two real terms are in the document and a whitespace tokenizer finds **neither**. So
Latin runs become words and Thai runs become overlapping 3-character n-grams.

The third line is the important one. `ทักษะ` happens to be followed by a colon, so it
*is* a standalone token — meaning a test written with that term alone passes against a
tokenizer that is wrong for Thai. **That is the two-column fixture with no header, in
a new costume**, and it is the fourth time this project has been offered a fixture that
proves nothing. The Thai test cases deliberately use terms buried mid-run.

### The property worth protecting

**Retrieval is a hint, never a gate.** `retrieve` scores every document and returns all
of them ordered; it never drops the tail.

A filtering retriever is tempting — it is what "pre-filter" sounds like — and it is the
same failure as a UI that hides `excluded` screenings, only worse: a person disappears
before anyone has looked, and nothing records that they were there. Choosing a cut-off
is the caller's decision, made in the open.

The related guarantee: retrieval makes **no claim about anyone**. Delete the module and
every verdict in the system is unchanged. That is precisely what makes it safe for it
to be approximate, and it is why it needs no evidence resolution.

### Four decisions, each confirmed load-bearing

| Mutation | Cases that fail |
|---|---|
| Tokenize Thai by whitespace | **5** |
| Filter out zero scorers (hint → gate) | **9** |
| Drop the resume-id tie-break | **2** |
| Let `job.description` steer retrieval | **1** |

The second one fails through the HTTP route as well as the function, which is the
useful part: the property is defended where a caller would actually notice it.

### Verified in the containers

`api` rebuilt first, `/openapi.json` lists the route, startup log reads
`retrieval=lexical`. Then, over three extracted resumes against a job whose only terms
are a Thai requirement and `PostgreSQL`:

```
resume_th.pdf          score=1.0749   matched=[งาน Backend ที่เกี่ยวกับระบบชำระเงิน, PostgreSQL]
resume_en.pdf          score=0.7313   matched=[งาน Backend ที่เกี่ยวกับระบบชำระเงิน, PostgreSQL]
resume_two_column.pdf  score=0.0      matched=[]
```

Two things land at once there. The Thai requirement really did match a term buried in
an unbroken run — the n-gram tokenizer doing its job on real data rather than in a
fixture. And `resume_two_column.pdf` contains **every word of that job's description**
(`Kubernetes Terraform gRPC`) and still scored 0.0: had the description steered
retrieval it would have ranked first. The decision was watched, not asserted.

`psql` afterwards: **zero** judging calls for the job. The ordering cost one query.

### M3, in one table

| Slice | Model call? | Migration? |
|---|---|---|
| 1 Jobs and requirements | no | `0004` |
| 2 Requirement-level judging | **yes** | `0005` |
| 3 Screening on the worker | **yes** | `0006` |
| 4 Ranking | no | no |
| 5 Thin web UI | no | no |
| 6 Retrieval | no | no |

**Half the milestone spends nothing at run time**, and the last three slices needed no
schema change at all. That is not luck: slices 1–3 stored `document_text`, `page_spans`
and the full `Judgment`, so everything after them was a pure function over rows that
already existed.

### Still open, in order

1. **M4 — backend depth.** Its `PLAN.md` entry is still a draft reconstructed from the
   README. M3's scope review with the owner is the reason that milestone went cleanly;
   do it again before writing code. HANDOFF §9 lists four things to know first.
2. **The visibility timeout** (M5) is now the oldest open item and still **the only one
   that can strand a user's data with no way back through the API**.
3. Next 15 → 16 for the postcss and sharp advisories. A framework major.
4. M6's evaluation stays out of the critical path with its one-week timebox. Nothing in
   this slice measures whether the retrieval *order* is good — only that it is
   deterministic, explainable and free. Do not let that gap quietly promote M6.

### Worth knowing next time

- **`GET /jobs/{id}/candidates` joins filenames client-side**, on the assumption that
  every screened resume belongs to the caller. True in M3, and exactly the assumption
  M4's RBAC breaks.
- Lexical scoring is in-memory and linear in total document length per request. Right
  at one recruiter's pile, wrong at thousands per job — which is what the seam is for.
- The throwaway account was deleted, and the stack is left rebuilt from current code
  with `retrieval=lexical` in the startup log.

### Advice for the owner

- **Measure the thing you are about to build on — again.** Every slice where this was
  done produced a design that survived, and this one is the clearest: five minutes with
  a probe script turned "tokenize the text" from a one-liner into the decision the whole
  module is organised around. The alternative was an implementation that looked correct,
  demoed correctly on `ทักษะ`, and silently failed on Thai phrases.
- **Name what a component is *not* allowed to do.** Retrieval is the first part of this
  system permitted to be approximate, and the only reason that is safe is that it makes
  no claim. Writing that down is what stops a future change from quietly letting it
  filter, or letting its score reach a verdict.
- **Ask what a passing test proves, not whether it passes.** `ทักษะ` would have gone
  green against the wrong tokenizer. Four sessions running, the fixture — not the code —
  has been the thing that was wrong.

---

## 2026-08-12 — M3 gets a face, and three checks that nearly lied

Slice 5. The matching engine had been fully usable over HTTP since slice 3 and
completely invisible: `web/` was still M1's single upload page. It now has `/jobs` and
`/jobs/[id]`, and M3 has only retrieval left.

Vitest **9 → 28**. Python suite unchanged at 411 — **no API change and no migration**,
which is the useful thing to notice about this slice.

### The data was already right, which is why this was cheap

`GET /jobs/{id}/ranking` already returned each entry's `RequirementJudgment`s —
verdicts *with* citation spans. So the list view needs no second request per
candidate, and `GET /screenings/{id}` is called only for `document_text`. Slice 4
wrote that into HANDOFF §9 as a thing to know before starting, and it was correct.

The one real refactor: `DocumentPane` took an `ExtractedProfile` and collected its own
spans, so it could not highlight a judgment. It takes `references: EvidenceRef[]` now.
That is the whole change, and it is why M1's citation highlighting works unmodified
for screenings — the offsets index into the same `document_text` either way.

### The trap, wearing slice 4's costume

`GET /screenings/{id}` returns the stored `Judgment` **verbatim**, with `must_have`
and `weight` frozen at judging time. Ranking re-keys both against the job's *current*
requirements. So rendering the verdict panel from the detail route — the obvious
choice, since that request is being made anyway for the document text — would make
weight edits appear to do nothing. No error, no stale flag, correct-looking numbers.

That is precisely the trap slice 4 documented on the server, one layer up. Writing it
down last time is what made it visible this time; the panel renders from the ranking
entry, and the detail route supplies `document_text` and nothing else.

### The test that could not fail, caught this time before shipping

All 28 tests passed on the first run, so — the habit — each decision was reverted and
the suite re-run:

| Mutation | Cases that fail |
|---|---|
| Flatten evidence without reading the verdict | **1** |
| Treat `weight`/`must_have` as fields the judge saw | **1** |
| Collapse 202 and 200 into `response.ok` | **1** |

The first one only fails **because the function was rewritten**. As originally
written, `collectJudgmentEvidence` was `flatMap(r => r.evidence)`, and the test
"a `not_evidenced` requirement contributes nothing" passed because the *fixture* had
an empty list. It asserted a property of the test data, not of the code — green
forever, catching nothing. It now filters on the verdict, and the test feeds it a
contradictory judgment carrying spans.

Worth stating plainly: the fix was to the **code**, not the test. Asking "could this
fail?" produced a better invariant — nothing is highlighted unless it produced a
verdict, checkable locally instead of assumed of the server.

### The UI's one job: say what things cost

A ranking is one query; a screening is a model call per resume. So:

- editing `weight` or `must_have` shows **"Free — reorders the ranking without
  re-judging anyone"**, in green, *before* saving
- editing `kind`, `label` or `detail` warns the screenings go stale
- edits stage behind a Save button, so the warning arrives before the write
- excluded screenings get an amber section, and the button reads **"Screen again —
  1 model call"**
- nothing anywhere loops `POST /jobs/{id}/screenings`

Screenings have no progress stream (only resumes do), so a queued one is followed by
polling `GET /jobs/{id}/screenings` — one request covering all of them.

### Verified in a browser, finally

The walkthrough had slipped three sessions as a follow-up. As a deliverable it took
twenty minutes, against the containers and live Gemini:

- The Thai requirement `งาน Backend ที่เกี่ยวกับระบบชำระเงิน` shows `Met`, citing the
  resume's own differently-worded `ดูแลระบบกระทบยอดการชำระเงินด้วย Python และ PostgreSQL`.
  Clicking the citation highlights exactly that line among 4 cited spans.
- `Kubernetes` reads "No citable evidence" — "That is not the same as the candidate
  lacking it." The `not_met` refusal, on screen.
- **The gate, visible:** with `Kubernetes` weighted 20, `resume_two_column` scores
  **83.3%, the highest on the page, and still ranks #3** below two candidates at
  16.7%. A gate, not a heavy weight — watched instead of inferred from a test.
- Weight edit → scores moved instantly, screenings stayed `completed`. Label edit →
  all three into "Not in the ranking (3)". **Restoring the label brought them back**,
  because the fingerprint is content-based rather than a timestamp.
- Afterwards, `psql`: **one `judge-v1` row per screening, `attempts=1`.** The whole
  session spent nothing.

**Both M2 renders nobody had watched are closed too.** `resume_two_column.pdf` reads
CONTACT/SKILLS through before EXPERIENCE rather than interleaving. And under
`STORAGE_BACKEND=minio`, an upload through the browser rendered normally with the
object in the bucket and **absent** from `/data/uploads`.

And the ranking ran entirely on real Gemini — all six `judge-v1` rows are
`provider=gemini`, which is the gap the last entry left open.

### Three instruments that lied, all in one script

The live-check script was wrong three times before it was right, and the first one
would have shipped as a passing result.

**1. A BOM-less `.ps1` is read in the ANSI codepage.** cp874 here, so the Thai literal
in the job payload was mangled *before it was sent*. The check printed a Thai
round-trip and `psql` said **90 chars / 240 bytes** where 36 / 90 belonged. This is
worse than the 2026-08-08 mojibake, which was only display: here the wrong bytes were
genuinely stored. Fix: keep the payload in a `.json` file and post its bytes.

**2. Assigning an `if` expression unrolls an array.**
`$x = if (…) { $bytes } else { … }` sends the result through the pipeline, which
re-collects `byte[]` as `Object[]`; `Invoke-WebRequest` posts its `ToString()` and the
server reports a JSON error at position 4 — it had parsed `123`, the `{`. My first
diagnosis blamed splatting and was wrong; a two-line probe showed splatting is fine.
Cast `[byte[]]`. (And do not name the temporary `$raw` in a function with a
`[switch]$Raw` parameter — PowerShell is case-insensitive and silently ate the switch.)

**3. A function that writes output *and* returns a value returns both.** So
`$before = Show-Ranking "as judged"` captured the printed table into the variable and
the most important output of the check simply never appeared.

### Still open, in order

1. **Slice 6 — retrieval**, the last of M3. HANDOFF §9 now lists four things to know
   first, the sharpest being that retrieval decides *who is worth paying to judge* and
   must not touch what evidence a screening sees.
2. **The visibility timeout** for a worker that dies mid-job (M5). Still the last §11
   follow-up and still **the only open item that can strand a user's data with no way
   back through the API**.
3. Next 15 → 16 for the remaining postcss and sharp advisories. A framework major.
4. M4–M6 in `PLAN.md` are still a draft reconstructed from the README. M3's scope
   review paid for itself; do the same before building to any of them.

### Worth knowing next time

- **`GET /resumes` is how the ranking table gets filenames.** Ranking carries
  `resume_id` only, and in M3 every screened resume belongs to the caller, so one
  request and a client-side join covers it. That stops being true when M4's RBAC lets
  a recruiter screen someone else's resume.
- A resume that is not `extracted` cannot be screened — the worker raises
  `NotScreenable` and the retry policy treats it as permanent. The UI says so instead
  of offering a button that can only fail.
- The throwaway account and its two jobs were deleted afterwards, and the stack was
  put back to `storage=local` matching `.env`, confirmed in the worker log.

### Advice for the owner

- **Write the trap down and you will recognise it in a new costume.** Slice 4's
  "read weights from the job, not the stored result" was recorded in HANDOFF §5 purely
  as a server decision. That paragraph is the only reason the same mistake was obvious
  one layer up, where the tempting shortcut was different but the silent failure was
  identical. Documentation earned its keep here in a way a test could not have.
- **When a test cannot fail, fix the code rather than the test.** The instinct is to
  write a cleverer assertion. The better question is why the property is not guaranteed
  where it is used — and the answer produced a genuinely stronger invariant.
- **A check that produces a *plausible* result is more dangerous than one that
  errors.** The Thai script bug printed a confident round-trip. Every one of this
  project's instrument lessons has this shape, and the defence is the same each time:
  go to the store that cannot lie, and compare bytes rather than eyeballs.

---

## 2026-08-08 — ranking lands, and it costs nothing to run

Slice 4. Screenings are now ordered into a ranking, which is the point the milestone
stops producing one verdict at a time and starts answering the question the product
is actually for: *who should I look at first?*

Suite **379 → 411**. No migration, no new table, no model call — the whole slice is a
pure function over rows that already existed.

### The trap that would have shipped quietly

`RequirementJudgment` stores `must_have` and `weight` alongside each verdict, frozen
at judging time. Reading them back out of `Screening.result` is the obvious
implementation — the data is right there, one `model_validate` away.

It is also wrong, and wrong in the way this project fears most: **it fails silently.**
`requirements_fingerprint` deliberately excludes `must_have` and `weight`, so editing
a weight leaves every screening `is_stale=false` — correctly, because no verdict
changed. But the stored JSON keeps the old number forever. A ranking built from it
would respond to a weight edit by doing absolutely nothing, with no error, no stale
flag and no way to tell from the outside.

So ranking reads both from the current `JobRequirement` rows. Which raises the join
question, and the obvious answer is wrong too: `requirement_id` is not reliable,
because the fingerprint excludes ids on purpose ("deleting a requirement and typing
the identical one back asks the same question"), so a *current* screening can carry
ids the job no longer has. What the fingerprint does cover is `(kind, label, detail)`
**and their order** — and `verify()` emits exactly one judgment per requirement in
requirement order. **The join is by position.** A length mismatch is excluded as
`malformed` rather than joined against the wrong requirement.

Both of those are one-line decisions with no visible symptom when they are wrong,
which is exactly the class HANDOFF §5 exists to record.

### The three decisions, each confirmed load-bearing

All 32 tests passed on the first run, so — following the habit from two sessions ago
— each decision was reverted and the real suite re-run:

| Mutation | Cases that fail |
|---|---|
| Read `must_have`/`weight` from the stored `result` | **5** |
| Treat `must_have` as a ×100 weight instead of a gate | **3** |
| Drop the trailing `screening_id` tie-break | **2** |

The third one is the interesting one, because it started at **1**. The determinism
test that *should* have caught it — "input order does not change the result" — used
three candidates with three distinct scores, so there was nothing to be stable about
and any sort at all passed it. Python's sort being stable meant the test could never
have failed. Rewritten with two candidates deliberately tied, it now catches the
mutation. **A test that cannot fail is worse than no test, because it is counted.**

### Verified by running it

Rebuilt `api` and `worker` first, confirmed `/openapi.json` lists the route and all
four schemas, then against the containers: a job of five requirements (two must-have,
one Thai label round-tripping at 10 chars) over three resumes.

- `resume_en` and `resume_th` both 3/5 with the gate passed; `resume_multipage` 0/5,
  gated out, ranked last. The two that **tie at 0.6000** are separated by the
  screening-id tie-break — the total order doing its job on real data rather than in
  a fixture.
- Weight 1.0 → 20.0 on one requirement: every score moved (0.6000 → 0.9167), all
  three screenings stayed `is_stale=false` with `attempts=1`, and **`psql` shows
  exactly one `judge-v1` row per screening** after two ranking requests plus the
  patch. The recompute really was free, checked in the store rather than inferred
  from the API.
- Changing that requirement's **label** instead: all three into `excluded` with
  `reason=stale`, `ranked` empty. A second account gets 404.

### The Gemini daily quota ran out mid-run

Worth recording because the failure looks like a bug and is not. The first live run
dead-lettered two screenings on `429 RESOURCE_EXHAUSTED`; the obvious reading is the
per-minute cap (5/min), so the script was rewritten to pace itself and replay dead
letters. It failed again — and the quota id in the second error was different:
`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, **20 per day**. Pacing cannot fix
a daily cap.

The run was finished on `LLM_PROVIDER=fake` as a command-line override, which is
adequate *for this slice specifically* — ranking makes no model call at all, so the
provider is not part of what it needed to prove — and `resume_en.pdf` had already
completed against real Gemini at 3/5 met, 0 dropped before the quota went. But nobody
has yet watched a ranking built entirely from Gemini judgments, and that is written
into HANDOFF §1 rather than left implied.

**Read the quota id, not just the 429.** Two different limits share one status code
and only one of them is worth waiting out.

### Still open, in order

1. **Push slice 4 and watch CI.** One commit, and CI has never seen any of it. The
   suite is 411 locally; the number to check on the runner is that it is *the same*
   with no Tesseract, no database, no MinIO and no key. No migration this time, so
   the SQLite step that caught `0006` has nothing new to chew on — but the routes,
   the schemas and `mypy` all do.
2. **Slice 5 — the thin web UI**, and it absorbs the browser walkthrough that has now
   slipped three sessions. Two-column and MinIO are both verified at the HTTP level
   and in the containers, and **no human has watched either render**. `PLAN.md` says
   the walkthrough is part of this slice rather than a follow-up to it, on purpose.
   HANDOFF §9 lists the four things to know first — the useful one being that
   `GET /jobs/{id}/ranking` already returns citations per candidate, so a list view
   needs no second request per row.
3. **Re-run the live ranking check against real Gemini** once the daily quota resets.
   Everything about ranking is provider-independent — it makes no model call — but
   nobody has yet seen a ranking assembled entirely from Gemini judgments, and that
   is exactly the kind of gap this project has been bitten by before. Twenty minutes
   with `scratchpad/live_ranking.py` as the starting point.
4. **Slice 6 — retrieval**, the last of M3.
5. **The visibility timeout** for a worker that dies mid-job (M5). Still the last §11
   follow-up and still **the only open item that can strand a user's data with no way
   back through the API** — a row stuck at `processing` is skipped by redelivery,
   409s on retry, and dedupes on re-upload.
6. Next 15 → 16 for the remaining postcss and sharp advisories. A framework major;
   belongs with the web work rather than squeezed into it.

### Worth knowing next time

- **`GET /resumes/{id}` returns `ProfileOut`, not `ResumeOut`** — the status lives at
  `body["resume"]["status"]`. Cost one failed script run.
- The throwaway accounts were deleted afterwards (five of them, cascading to zero
  jobs and zero screenings left), and the stack is back on `provider=gemini` matching
  `.env`, confirmed in the worker log rather than assumed.

### Advice for the owner

- **The dangerous bugs here are the ones with no symptom.** Both of this slice's real
  decisions — weights from the job, join by position — produce a system that looks
  completely healthy when they are wrong: correct-looking numbers, no errors, no stale
  flags. The defence that worked was asking "what would I see if this were wrong?"
  and, when the answer was "nothing", writing the test that makes it visible.
- **Check that your test could fail, not just that it passes.** The tie-break test was
  green for a mutation it was written to catch. Green is not evidence until you have
  seen it go red once — this is the fourth session in a row that lesson has paid, in a
  fourth costume.
- **Cheap things should stay cheap.** Ranking costs one query, and keeping
  `must_have`/`weight` out of the fingerprint is what protects that. If a future
  change starts re-judging on a weight edit "for consistency", the whole reason this
  slice is instant has been traded away for nothing.

---

## 2026-08-08 — screening lands, and M3 is usable over HTTP

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

### A bug found by pushing, again

Migration `0006` round-tripped on real Postgres, `alembic check` was clean, the row
was queried there, and the whole slice was verified live in the containers. CI still
went red.

`.github/workflows/ci.yml` has a step nobody had written down anywhere:
**`Verify migrations apply and reverse` runs `alembic upgrade head` → `downgrade base`
against SQLite.** And SQLite cannot ALTER a constraint onto an existing table at all,
so `op.create_foreign_key` on `llm_call_logs` passed on Postgres and failed the
build.

Two things worth keeping:

1. **Declaring the foreign key inline on the column does not fix it.** That was the
   obvious first attempt and it fails identically, because alembic adds the column
   and *then* adds each of its constraints as a separate statement. `op.batch_alter_table`
   is the answer: ordinary ALTERs on Postgres, copy-and-move rebuild on SQLite. The
   rebuild was checked rather than trusted — `pragma foreign_key_list` and
   `index_list` confirm both foreign keys and all three indexes survived.
2. **"Verified on Postgres" was a half-check that felt like a whole one.** The
   handoff's own rule said a migration is not verified until it round-trips on real
   Postgres, which is true and was followed — and was not sufficient. §10 now says
   both dialects, with the one-line local command.

Same family as the `setup-uv` finding: nothing local could have told me, and CI's own
output said it immediately.

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
- **Ask what your check does *not* cover.** "Verified on real Postgres" was the rule,
  it was followed, and it still missed a migration that cannot run on the dialect CI
  uses. The previous advice here was to ask what instrument you used; the sharper
  version is to ask what the instrument cannot see. Three sessions running, the answer
  has been "the environment I am not standing in" — which is the argument for pushing
  early, since CI is the cheapest way to stand somewhere else.

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
