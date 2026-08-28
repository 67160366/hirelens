# docs/pitch — the 3-minute pitch deck and its demo material

Not part of the application. Everything here is reproducible from the scripts in
this folder plus a running stack.

| File | What it is |
|---|---|
| `deck.template.html` | The deck, with `{{IMG:name}}` placeholders. **Edit this one.** |
| `deck.html` | Built output — the same page with every screenshot inlined as a data URI. Generated; do not edit by hand. |
| `deck.pdf` | 11 landscape pages, printed from `deck.html`. |
| `build.py` | Inlines `shots/*.webp` into `deck.html`. Run after any template edit. |
| `script-th.md` | The spoken script, with cue lines, a pacing table and a cut list. |
| `shots/*.webp` | Screenshots of the running application. **Generated — see below.** |
| `shoot.py` | Re-takes them over CDP against a running stack. |
| `sample/generate_sample.py` | Builds `sample/sample_resume_th.pdf`. |
| `sample/compare_parse.py` | Prints what a plain text extractor makes of that resume, beside what the pipeline makes of it. |

```bash
api/.venv/Scripts/python.exe docs/pitch/sample/generate_sample.py
api/.venv/Scripts/python.exe docs/pitch/sample/compare_parse.py
api/.venv/Scripts/python.exe docs/pitch/shoot.py     # needs the demo stack up
api/.venv/Scripts/python.exe docs/pitch/build.py
```

`deck.pdf` is `*.pdf`-gitignored, so it is rebuilt rather than pulled. Chrome's own
print honours the deck's `@page size: 297mm 167mm` and lands the same 11 pages:

```bash
"/c/Program Files/Google/Chrome/Application/chrome.exe"   --headless=new --disable-gpu --no-pdf-header-footer --virtual-time-budget=10000   --print-to-pdf=docs/pitch/deck.pdf file:///.../docs/pitch/deck.html
```

## The person in `sample_resume_th.pdf` does not exist

`CLAUDE.md` forbids a real person's resume anywhere in this repository, and that
holds for demo material more strictly than for fixtures, not less — a slide has a
wider audience than a test run. What is taken from real postings and real resume
templates is the **shape**: the section order, the sidebar, the way dates and
metrics get written, and the two-column layout with a full-width header band that
Canva and Word templates produce.

The posting seeded alongside it is written from the conventions in real Thai
listings (`หน้าที่ความรับผิดชอบ` / `คุณสมบัติผู้สมัคร` / `จะพิจารณาเป็นพิเศษ`, a stated
degree and years of experience) and from a public English JD template. It advertises
a role at HireLens itself, which is what the careers site is.

## What slide 4 measures

`compare_parse.py` is the source of the two panes on that slide, and its numbers are
measured on every run rather than written into the deck once:

- **3 lines** in the plain extraction fuse the sidebar into the work history —
  `pytest, Grafana บริษัท ไทยเพย์เมนต์ เกตเวย์ — Backend Engineer` is a sentence the
  document does not contain.
- **0** after `app/pipeline/layout.py` cuts the page into bands and then columns.
- **1 of the 7** quotes the screening cited cannot be found in the plain extraction
  at all: the education line, which only exists as a contiguous run once the columns
  are read one after the other. **Re-measured 2026-08-29** against the screening now on
  the deck — still 1 of 7, still `วิศวกรรมศาสตรบัณฑิต / สาขาวิศวกรรมคอมพิวเตอร์`, and the
  other six are found even in the fused text.

## How the screenshots are taken

**Re-shot 2026-08-29** against the demo stack (`docs/RUNBOOK.md` §9). The previous set
was taken on 2026-08-22 and four of the six had gone stale underneath the deck: the
workbench was rebuilt to lead with the ranking and fold the requirement editor away,
`/me` lost the second job board, and `/careers/[id]` moved onto `PostingScreen`.
`landing.webp` was **not** re-taken — the page's markup has not changed since, only the
internals it was refactored into.

They are driven by `shoot.py` rather than taken by hand, and that is the point: Chrome's
own `--screenshot` cannot sign in, so the script drives headless Chrome over CDP —
`Network.setCookie` for the session, `Runtime.evaluate` for the identity marker
`lib/auth.ts` keeps beside it — and frames each shot with `getBoundingClientRect` on a
named component instead of a hand crop. A re-shoot lands on the same frame next time.

Two things it has to get right, both learned by getting them wrong:

- **Scroll to the top before measuring.** Several panes are `position: sticky`; a clip
  taken after scrolling to one captures the nav bar painted over the frame.
- **A tall frame is a small frame.** `.shot img` in the deck is height-constrained with
  `width: auto`, so a screenshot twice as tall renders half as wide. The receipt is
  cropped to roughly 1.22:1 for that reason.

## Provenance of the numbers on the deck

- The screening on slides 7 and 10 ran against **real Gemini** (`gemini-3.6-flash`),
  two calls total: one extraction, one judging.
- **Slide 9's ranking is mixed on purpose, and it is worth stating.** Two of its five
  screenings ran on real Gemini and three on the `fake` provider. Nothing on that slide
  claims a provider, and `fake` is not a stub — it quotes the real document, so the
  evidence, the scores and the gate are all real. The alternative was spending eight
  more calls of a 20-a-day free tier to change no number a viewer can see.
- Slide 8's refused claim was produced with `FAKE_MODE=hallucinating`, which attaches
  a quote that is not in the document on purpose. Forcing a fresh run needs the stored
  screening to go stale, so a temporary eighth requirement was added and then removed —
  removing it restores the original `requirements_fingerprint`, and with it the Gemini
  screening behind slides 7 and 10.
- Slide 3's outside figures are cited on the slide: Harvard Business School ×
  Accenture, *Hidden Workers: Untapped Talent* (2021), and Reuters (2018) on Amazon.
- **No hallucination-rate figure is published.** It is measured on this project's own
  synthetic corpus, and `docs/PLAN.md` refuses to publish it for the same reason M6
  was closed.
