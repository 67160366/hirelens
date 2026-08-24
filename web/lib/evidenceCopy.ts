/**
 * The guardrail's vocabulary in the reader's language.
 *
 * `lib/evidence.ts` owns the English wording and says why it lives in `lib/` at
 * all: a label defined inside a component is a label no test can reach. This file
 * is that decision extended one step, and the step is a real one rather than a
 * translation table — **the public site is Thai and the product screens are
 * English** (`docs/DESIGN.md` §8), so the same panel has to speak twice.
 *
 * It is a separate module rather than more exports in `evidence.ts` because the
 * two are read for different questions: what the words *mean* is `evidence.ts`,
 * which language they are in is here. `evidence.ts` stays the definition, and the
 * English half below is imported from it rather than retyped — a second copy of
 * those sentences is the one that drifts, which is the argument its own docstring
 * makes.
 */

import type { RejectReason } from "@/lib/api";
import {
  DROPPED_PANEL_EXPLANATION,
  droppedPanelTitle,
  droppedReasonLabel,
} from "@/lib/evidence";

export type Language = "en" | "th";

/**
 * Why a claim could not be traced, in Thai.
 *
 * A total `Record`, exactly as the English one is: adding a reason to
 * `RejectReason` fails the build here rather than rendering `undefined` on a
 * public page.
 */
const REJECT_LABEL_TH: Record<RejectReason, string> = {
  not_found: "ไม่มีข้อความนี้อยู่ในเอกสาร",
  too_short: "ข้อความสั้นเกินกว่าจะระบุที่มาได้",
  empty: "ไม่ได้ยกข้อความมาเลย",
  unknown_requirement: "อ้างถึงข้อกำหนดที่ไม่มีอยู่จริง",
};

/** The words one panel needs, in one language. */
export interface DroppedVocabulary {
  title: (count: number) => string;
  explanation: string;
  reason: (reason: RejectReason) => string;
  /** Prefixes the quote itself. It has to say that this is what the model
   *  *asserted*, not what the document says — the strike alone does not carry
   *  that, and the quote is set in the same face as a real citation. */
  claimed: string;
  /** Where a dropped claim carried no value to name. */
  noValue: string;
}

/**
 * The wording for a dropped-claims panel.
 *
 * The Thai half keeps the English half's care about *whose* mistake this is:
 * "ตัดออก" rather than "ผิดพลาด", because nothing here is a statement about the
 * candidate — these are claims the system refused to repeat.
 */
export function droppedVocabulary(language: Language): DroppedVocabulary {
  if (language === "en") {
    return {
      title: droppedPanelTitle,
      explanation: DROPPED_PANEL_EXPLANATION,
      reason: droppedReasonLabel,
      claimed: "claimed",
      noValue: "(no value)",
    };
  }
  return {
    title: (count) => `ตัดออก — หาที่มาในเอกสารไม่เจอ (${count})`,
    explanation:
      "โมเดลยืนยันข้อความพวกนี้ แต่ข้อความที่มันอ้างไม่มีอยู่ในไฟล์ เราจึงแสดงไว้ตรงนี้แทนที่จะทิ้งไปเงียบ ๆ",
    reason: (reason) => REJECT_LABEL_TH[reason],
    claimed: "โมเดลอ้างว่า",
    noValue: "(ไม่มีค่า)",
  };
}

/** The words the document pane needs, in one language. */
export interface PaneVocabulary {
  title: string;
  prompt: string;
  spanCount: (count: number) => string;
}

/**
 * The wording for the source-document pane.
 *
 * The pane is shared by the recruiter's workbench, the applicant's receipt and
 * the public demo, and the last of those is Thai. Its two sentences are the only
 * prose in it — the coordinate line under each citation stays as it is, because
 * `p1 · chars 168–221 · exact` is the same line in every language and translating
 * half of it would make it less legible, not more.
 */
export function paneVocabulary(language: Language): PaneVocabulary {
  if (language === "en") {
    return {
      title: "Source document",
      prompt: "Select a citation to locate it",
      spanCount: (count) => `${count} cited ${count === 1 ? "span" : "spans"}`,
    };
  }
  return {
    title: "เอกสารต้นทาง",
    prompt: "กดที่ข้อความอ้างอิงเพื่อดูว่าอยู่ตรงไหน",
    spanCount: (count) => `อ้างถึง ${count} ช่วง`,
  };
}
