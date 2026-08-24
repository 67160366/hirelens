import { describe, expect, it } from "vitest";

import { REJECT_REASONS } from "./evidence";
import { droppedVocabulary, paneVocabulary } from "./evidenceCopy";

/**
 * The panel that reports refused claims appears on a public Thai page and on the
 * English product screens, so the vocabulary has to be complete in both. A missing
 * Thai reason renders `undefined` beside a struck-through quote — on the one panel
 * whose job is to explain why something was refused.
 */
describe("droppedVocabulary", () => {
  it.each(["en", "th"] as const)("covers every reject reason in %s", (language) => {
    const words = droppedVocabulary(language);
    for (const reason of REJECT_REASONS) {
      expect(words.reason(reason), reason).toBeTruthy();
    }
  });

  it.each(["en", "th"] as const)("counts the refusals in its heading in %s", (language) => {
    expect(droppedVocabulary(language).title(2)).toContain("2");
  });

  it.each(["en", "th"] as const)("prefixes the quote as an assertion in %s", (language) => {
    const words = droppedVocabulary(language);
    expect(words.claimed).toBeTruthy();
    expect(words.noValue).toBeTruthy();
  });

  it("says different words in each language, so a missing translation is visible", () => {
    const en = droppedVocabulary("en");
    const th = droppedVocabulary("th");
    expect(th.explanation).not.toBe(en.explanation);
    expect(th.reason("not_found")).not.toBe(en.reason("not_found"));
    expect(th.claimed).not.toBe(en.claimed);
  });

  // Nothing in this panel is a statement about the candidate — these are claims
  // the *system* refused to repeat, and the English wording is careful about it.
  it("keeps the Thai wording off blame", () => {
    const th = droppedVocabulary("th");
    for (const word of ["ผิดพลาด", "ล้มเหลว", "โกหก"]) {
      expect(th.explanation).not.toContain(word);
      expect(th.title(1)).not.toContain(word);
    }
  });
});

describe("paneVocabulary", () => {
  it.each(["en", "th"] as const)("names the pane and prompts for a citation in %s", (language) => {
    const words = paneVocabulary(language);
    expect(words.title).toBeTruthy();
    expect(words.prompt).toBeTruthy();
  });

  it("counts the cited spans", () => {
    expect(paneVocabulary("en").spanCount(1)).toBe("1 cited span");
    expect(paneVocabulary("en").spanCount(4)).toBe("4 cited spans");
    expect(paneVocabulary("th").spanCount(4)).toContain("4");
  });

  it("says different words in each language", () => {
    expect(paneVocabulary("th").title).not.toBe(paneVocabulary("en").title);
  });
});
