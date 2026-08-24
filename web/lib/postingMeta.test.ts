import { describe, expect, it } from "vitest";

import type { Posting } from "./api";
import { postingMetadata, truncate } from "./postingMeta";

function posting(overrides: Partial<Posting> = {}): Posting {
  return {
    id: "p1",
    title: "Backend Engineer",
    description: null,
    location: "กรุงเทพฯ",
    published_at: "2026-08-20T00:00:00Z",
    requirements: [],
    ...overrides,
  };
}

describe("postingMetadata", () => {
  it("puts the posting's own title in the page title", () => {
    expect(postingMetadata(posting()).title).toBe("Backend Engineer · กรุงเทพฯ — HireLens");
  });

  it("leaves the location out when the posting has none", () => {
    expect(postingMetadata(posting({ location: null })).title).toBe(
      "Backend Engineer — HireLens",
    );
  });

  it("describes it in the employer's own words", () => {
    const meta = postingMetadata(posting({ description: "ทีมแพลตฟอร์มเอกสาร\nงานหลักคือ API" }));
    expect(meta.description).toBe("ทีมแพลตฟอร์มเอกสาร งานหลักคือ API");
  });

  it("says what the posting measures when nobody wrote a description", () => {
    const meta = postingMetadata(
      posting({ requirements: [{ kind: "skill", label: "Python", detail: null, must_have: true }] }),
    );
    expect(meta.description).toContain("1");
  });

  // A 404 and an unreachable API are the same absence here, and naming a document
  // nobody could read is exactly the kind of claim this project refuses.
  it("invents nothing for a posting it could not fetch", () => {
    expect(postingMetadata(null)).toEqual({});
  });
});

describe("truncate", () => {
  it("leaves a short description alone", () => {
    expect(truncate("short", 160)).toBe("short");
  });

  it("cuts on a word boundary in a language that has them", () => {
    expect(truncate("one two three four", 12)).toBe("one two…");
  });

  // Thai has no word spaces, so the boundary search finds nothing and the cut
  // stands where it fell. Falling back to the whole string, or to an empty one,
  // are both worse than a mid-run cut with an ellipsis.
  it("still cuts a run with no spaces in it", () => {
    const thai = "ก".repeat(200);
    const cut = truncate(thai, 160);
    expect(cut).toHaveLength(161);
    expect(cut.endsWith("…")).toBe(true);
  });
});
