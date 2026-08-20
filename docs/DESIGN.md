# Design

What HireLens looks like, and why. Written before the screens were built rather than
reconstructed from them — a design system that lives only in a stylesheet is a set of
decisions nobody can review.

Read this with `CLAUDE.md` (the product's one idea) and `docs/NOTES.md` (where the
product is going). The tokens themselves live in `web/app/globals.css`, which is the
single source of truth; this file says what they mean.

**Direction: precision instrument.** Ink and paper, dense, calm, confident. The product
sells the claim that it only says what it can prove, so the interface has to look like an
instrument rather than a pitch. That is not an argument for plain — it is an argument for
a particular kind of polish.

### The chosen expression: C · Console (2026-08-20)

Three directions were drawn on these tokens and shown side by side, each rendering the
*same* screening so they were comparable rather than three moods: **A · Instrument**
(dense, paper-white, hairline rules), **B · Editorial** (display type, the verdicts set as
a printed report), and **C · Console** (the recruiter's workbench with real elevation, an
accent-tinted selected row, and score bars). The owner chose **C**.

C is *a presentation of this palette, not a new one*. It was drawn on the dark half of the
tokens because that is where its density reads best, and that is the only reason.

**What C adds:** real elevation (`--shadow-raised`, already defined), an **accent**-tinted
selected row, and a score bar in the ranking.

**What C does not relax:** the three reserved meaning colours below, the refusals in §6,
colour never being the only signal, and the 4.5:1 floor in both themes.

**Both themes stay.** `globals.css` declares `color-scheme: light dark` and a complete dark
block; the light theme is C's same structure on paper. **A screen is not done until it has
been driven at 375 / 768 / 1440 in both themes.** "The app is dark now" is not what was
chosen and is not on offer.

The choice was made against a stated cost: of the three, C is the closest to generic SaaS.
What holds it away from that is the pair of rules at the end of §1 — written down once —
rather than restraint remembered screen by screen.

---

## 1. The one rule

**Colour carries meaning before it carries style.**

Three colours are reserved for what the system says about a document, and may never be
spent on decoration:

| token | means |
|---|---|
| `cited` | a quote the application located in the source document |
| `ambiguous` | a quote that matched in more than one place, reported rather than guessed at |
| `dropped` | a claim that could not be located, and was refused |

`accent` — the indigo used for navigation and actions — is deliberately a **different
hue** from all three. Nothing the product *asserts* about a person may ever be mistaken
for a button, and no button may borrow the colour of a verdict.

The one sanctioned exception is a destructive control, which borrows `dropped`: refusing
a claim and destroying a row read the same way to a person, which is *this cannot be
undone*.

### Two rules C makes explicit

Both follow from the rule above rather than amending it. C is what made them concrete, and
both were being broken in `components/RankingTable.tsx` on the day the direction was chosen.

**A selected row is tinted `accent`, never `cited`.** Selection is a control state. The
ranking's selected row was `bg-emerald-50 dark:bg-emerald-500/10` — the `cited` hue spent
on "you clicked this", which is precisely a colour serving both meaning and decoration.

**When the must-have gate fails, the score bar goes grey — never red.** A failed gate is a
fact about the posting's requirements, not a warning about the person, and nothing here may
render a candidate in the colour of a refused claim. The words beside it carry the meaning,
as always. This is the one rule that keeps C from being a dashboard.

---

## 2. Typography

**The whole IBM Plex superfamily**: Plex Sans for Latin, **Plex Sans Thai Looped** for
Thai, Plex Mono for quotes and offsets. Loaded through `next/font/google` in
`web/app/layout.tsx` and self-hosted from there.

Three reasons, in order of how much they matter:

1. **Thai and Latin have to look like one typeface.** Plex Sans is the Latin companion
   Plex Thai was drawn against, so a résumé line mixing Thai and English sits on one
   rhythm instead of visibly switching fonts mid-sentence. Pairing Plex Thai with Inter —
   which this repo did briefly — gives two different x-heights and stem weights in the
   same line.
2. **Looped is the conventional Thai reading form for body text.** The loopless cut reads
   as display or "tech"; on a site addressed to Thai applicants, body copy is looped.
3. **Every quote and every character offset is set in mono, with tabular figures.** A
   citation is a claim about exact characters, and two offsets differing by one must not
   be able to look identical.

Plex Sans Thai has **no variable weight** (checked in
`next/dist/compiled/@next/font/dist/google/font-data.json`), so 400 / 500 / 600 are
enumerated — exactly what the tree uses.

### Scale

`micro` 11px · `xs` 12px · `sm` 14px (body) · `section` 15px (panel headings) ·
`lg`/`xl` for page titles · `display` fluid, for the landing headline only.

`text-[10px]` and `text-[12.5px]` are retired: an arbitrary size is a decision nobody
recorded.

---

## 3. Palette, measured

Every value was computed rather than asserted (WCAG 2.x relative luminance, this repo's
own tokens against its own grounds):

| token | light, on paper | dark, on paper |
|---|---|---|
| `ink` | 18.09:1 | 17.32:1 |
| `ink-muted` | 7.30:1 | 12.69:1 |
| `ink-faint` | **4.59:1** | 7.49:1 |
| `accent` | 6.02:1 | 6.33:1 |
| `cited` | 5.25:1 | 9.83:1 |
| `ambiguous` | 4.81:1 | 11.32:1 |
| `dropped` | 6.02:1 | 7.02:1 |

Every token clears WCAG AA (4.5:1) in both themes.

`ink-faint` at 4.59:1 is the tightest in the set, and it is what the *smallest* text
uses. So one rule falls out of the table:

> **The citation coordinate line uses `ink-muted`, never `ink-faint`.**

`p1 · chars 161–214 · exact` is the product's claim of traceability. Before this it was
10px at roughly 2.6:1 — the least legible text on a screen whose entire purpose is that
line. It is defined once, as `.evidence-coordinates`, so it cannot drift back.

---

## 4. Motion

**Motion explains the mechanism. It never decorates.**

- Durations: `--duration-fast` 120ms for a control responding, `--duration-base` 220ms for
  a state change, `--duration-slow` 420ms for something entering.
- Ease-out entering, ease-in leaving, ease-in-out for a thing moving between its own
  states.
- Animate `transform` and `opacity`. Nothing else — **with one recorded exception**, below.
- Everything is neutralised under `prefers-reduced-motion: reduce`, in one block at the
  bottom of `globals.css`. Motion is an enhancement; the product works without it.

### The one exception, and why it is not a loophole

Motions 1 and 2 below both paint with **`background-size`**. The transform version needs
an absolutely-positioned overlay, and an overlay cannot follow inline text that wraps —
which the two places this is used both do. `ชำระเงิน` sits inside an unbroken
31-character Thai run, and a fabricated quote is long enough to take two lines; a
transform sweep would paint the first line box and leave the rest untouched. With
`box-decoration-break: clone` each line box paints its own, which is what a highlighter
does. Measured: the struck quote in `resume_multipage.pdf` occupies **2 line boxes** and
both carry the line.

The rule exists to keep animation off the layout and paint path. `background-size` on a
short inline run is not that, and it is confined to these two recipes in `globals.css`.
Anything else still answers to the rule as written.

### The four motions that *are* the product

The rest of the interface stays still. These four earn their place because each one shows
something the product would otherwise merely assert:

1. **A citation is selected** → its span sweeps in left-to-right in the document pane and
   the coordinate line reveals beneath it. The eye is led *to* the text, not away from it.
   `.cite-sweep` plus `animate-fade-up` on `.evidence-coordinates`.
2. **A claim is dropped** → the strike-through is **drawn** rather than appearing.
   Watching a fabrication get refused is the whole argument; a strike that is simply
   there is a styling choice. `.claim-struck` — and note it is a painted rule rather than
   `text-decoration: line-through`, which cannot be animated at all.
3. **Verdicts land** in list order with a short stagger, so a reader sees they were
   decided one requirement at a time rather than handed down as a block.
4. **Dashboard figures count up** from zero — a number that was queried, not asserted.

Anything else that moves has to justify itself against this list.

---

## 5. Floors

Each of these is written down because this codebase has already failed it once, and the
audit that found them is summarised in `docs/NOTES.md`.

- **4.5:1 minimum**, both themes, measured not guessed.
- **A real focus indicator on every control.** `outline-none` plus a 1px border tint is
  not perceivable and fails WCAG 2.4.11. One recipe, `ring-focus`, applied everywhere.
- **24×24 minimum target**, and 32×32 for anything destructive.
- **Colour is never the only signal.** A tone always arrives with a word.
- **A live region exists before it has anything to say** — a container mounted at the
  same moment as its text is not announced. `Banner` derives its `role` from its tone, so
  six separate omissions became one decision made once.
- **Every interactive row is reachable from a keyboard.** `aria-current` on an element
  nothing can focus is worse than silence.

---

## 6. Refused

Recorded so they read as decisions rather than oversights:

- Gradient heroes, glassmorphism, glow, decorative parallax.
- Any colour serving both meaning and decoration.
- Any animation attached to a claim that is not that claim's own evidence.
- Marketing polish that outruns what the system can back up. A screening product that
  looks like a crypto landing page argues against its own thesis — the same instinct as
  refusing to publish a hallucination rate measured on our own synthetic corpus.

---

## 7. Primitives

`web/components/ui/` — `Card`, `Button`, `Banner`, `Badge`, `Stat`, plus `lib/cn.ts`.

They exist because the tree grew 14 button recipes for five intents, 21 hand-written card
strings across nine padding recipes, eight banner recipes across three tones, and two
different components both named `Panel`. A caller may still pass `className`; it is
appended, so it wins by CSS order rather than by a merge algorithm nobody can predict
from the call site.

The rule that keeps them: a page may not hand-write a card, a button or a banner.

---

## 8. Language

**Thai-first, and it applies to the public pages only.**

The audience for the careers site is Thai applicants, so the public pages lead in Thai:
`<html lang="th">`, a Thai headline with a short English line beneath, one set of copy.
**Not** a `[locale]` segment — it costs roughly one extra large slice plus permanent copy
maintenance, for an audience that did not ask for two languages.

**The existing internal screens — `/`, `/jobs`, `/jobs/[id]`, `/applications`, `/metrics` —
keep their English copy**, decided 2026-08-20 when the token migration was scoped. Copy is
its own slice. Folding a translation into each screen's migration would make every one of
them two changes at once, and a screen that changed both its paint and its words is a screen
nobody can review.

Either way the typography is already settled by §2: one superfamily, so a line mixing Thai
and English sits on one rhythm whichever language leads.
