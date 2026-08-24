import type { Metadata } from "next";

import type { Posting } from "@/lib/api";

/** How long a shared description may run before it is cut. */
const DESCRIPTION_LIMIT = 160;

/**
 * What a posting looks like when it is shared rather than opened.
 *
 * A careers site is passed around in chat windows and search results, and until
 * now every posting shared as *"HireLens — explainable resume screening"* with no
 * description — the layout's title, because the advertisement arrived after
 * hydration and metadata is decided before that.
 *
 * Two refusals worth stating, both of which a template would have got wrong:
 *
 * - **A posting that could not be fetched gets the site's own title**, not
 *   "Posting" or an id. Inventing a name for a document nobody could read is the
 *   shape of claim this project exists to refuse. (Which *kind* of absence it was
 *   is `lib/serverApi`'s business: a missing posting answers a real 404 before
 *   this is ever asked.)
 * - **The description is the employer's own words, trimmed**, never a generated
 *   summary. What is advertised has to be what was written — and a screening
 *   product that paraphrases its own postings in the one place people read them
 *   without opening them is arguing against itself.
 */
export function postingMetadata(posting: Posting | null): Metadata {
  if (posting === null) return {};

  const location = posting.location?.trim();
  const title = location ? `${posting.title} · ${location}` : posting.title;
  return {
    title: `${title} — HireLens`,
    description: describe(posting),
  };
}

function describe(posting: Posting): string {
  const written = posting.description?.replace(/\s+/g, " ").trim();
  if (written) return truncate(written, DESCRIPTION_LIMIT);

  // No description written: say what the posting measures instead of nothing.
  // The count is a fact about the advertisement, not a claim about anybody.
  const count = posting.requirements.length;
  if (count === 0) return "ตำแหน่งที่ HireLens เปิดรับ";
  return `ตำแหน่งที่ HireLens เปิดรับ · วัดจาก ${count} ข้อ ที่บอกไว้ก่อนตั้งแต่ในประกาศ`;
}

/** Cut on a word boundary where there is one, so a description never ends mid-word. */
export function truncate(text: string, limit: number): string {
  if (text.length <= limit) return text;
  const cut = text.slice(0, limit);
  const lastSpace = cut.lastIndexOf(" ");
  // Thai has no word spaces, so a run with none is cut where it is rather than
  // thrown away — `lastIndexOf` returning -1 is the common case in Thai, not an
  // edge one.
  const body = lastSpace > limit / 2 ? cut.slice(0, lastSpace) : cut;
  return `${body.trimEnd()}…`;
}
