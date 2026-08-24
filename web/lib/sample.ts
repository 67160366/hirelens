/**
 * The two lines `/how-we-screen` illustrates the mechanism with.
 *
 * **Copied out of the committed fixture, not typed from memory.** The document
 * below is the text of `api/tests/fixtures/resume_th.pdf` as
 * `api/tests/fixtures/generate.py` writes it. A previous mockup spelled the
 * employer `บริษัท เอชีเอ็มดี โลจิสติกส์`, which the fixture does not contain — and on
 * a product whose entire claim is *the quoted text exists in the document*, an
 * illustration with invented source text argues against its own thesis.
 *
 * They live in `lib/` because `web/` has vitest and no DOM: the two properties
 * the page rests on — the cited quote **is** in the document and the fabricated
 * one is **not** — are assertions a test can make here and cannot make about a
 * string inside a component.
 *
 * Nobody in it exists. `CLAUDE.md` forbids a real person's resume anywhere in
 * this repository, and that binds harder for a page a stranger can open than for
 * a test run.
 */

/** The sample resume, exactly as the fixture generator writes it. */
export const SAMPLE_DOCUMENT = `สมชาย ใจดี
วิศวกรซอฟต์แวร์อาวุโส  |  somchai.j@example.com  |  กรุงเทพมหานคร

ประสบการณ์ทำงาน
บริษัท เอซีเอ็มอี โลจิสติกส์ — วิศวกรซอฟต์แวร์ (ม.ค. 2564 - มี.ค. 2567)
  ดูแลระบบกระทบยอดการชำระเงินด้วย Python และ PostgreSQL
  รองรับธุรกรรม 40,000 รายการต่อวัน

ทักษะ
Python, FastAPI, PostgreSQL, Docker, การออกแบบระบบ`;

/** A quote that is in the document, so it survives and gets highlighted. */
export const SAMPLE_QUOTE = "ดูแลระบบกระทบยอดการชำระเงินด้วย Python และ PostgreSQL";

/**
 * A quote that is **not** in the document, so it is dropped.
 *
 * Written the way a fabrication actually reads — plausible, specific, and about
 * something the document never mentions. A nonsense string would make the refusal
 * look easy; the point is that this one is only refusable by looking.
 */
export const SAMPLE_FABRICATION = "เคยดูแลทีมวิศวกร 8 คนและวางระบบ Kubernetes ทั้งองค์กร";

/**
 * The document split around the surviving quote: before it, and after it.
 *
 * The page paints the highlight over the middle piece, so the highlight can only
 * ever sit on text the document really contains. Returns `null` if the quote is
 * absent, and the page then renders the document unmarked — a highlight over
 * text nobody located is the one thing this page may not show.
 */
export function splitAroundQuote(
  document: string,
  quote: string,
): { before: string; after: string } | null {
  const at = document.indexOf(quote);
  if (at < 0) return null;
  return { before: document.slice(0, at), after: document.slice(at + quote.length) };
}
