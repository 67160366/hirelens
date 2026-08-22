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
| `shots/*.webp` | Screenshots of the running application. |
| `sample/generate_sample.py` | Builds `sample/sample_resume_th.pdf`. |
| `sample/compare_parse.py` | Prints what a plain text extractor makes of that resume, beside what the pipeline makes of it. |

```bash
api/.venv/Scripts/python.exe docs/pitch/sample/generate_sample.py
api/.venv/Scripts/python.exe docs/pitch/sample/compare_parse.py
api/.venv/Scripts/python.exe docs/pitch/build.py
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
  are read one after the other.

## Provenance of the numbers on the deck

- The screening on slides 7 and 10 ran against **real Gemini** (`gemini-3.6-flash`),
  two calls total: one extraction, one judging. `.env` was switched back to `fake`
  afterwards.
- Slide 8's refused claim was produced with `FAKE_MODE=hallucinating`, which attaches
  a quote that is not in the document on purpose.
- Slide 3's outside figures are cited on the slide: Harvard Business School ×
  Accenture, *Hidden Workers: Untapped Talent* (2021), and Reuters (2018) on Amazon.
- **No hallucination-rate figure is published.** It is measured on this project's own
  synthetic corpus, and `docs/PLAN.md` refuses to publish it for the same reason M6
  was closed.
