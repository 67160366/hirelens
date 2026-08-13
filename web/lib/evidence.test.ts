/**
 * Tests for how the guardrail's own evidence is worded.
 *
 * Everything here fails *quietly* when it is wrong. A reason with no label renders
 * the word `undefined` beside a real claim; a "clean" flag derived from the rounded
 * hallucination rate calls a document with a dropped claim clean; and a model-call
 * count read from the wrong counter reports a job retry as a second model call.
 * None of the three throws, and none of them is visible in a screenshot.
 */

import { describe, expect, it } from "vitest";

import type { EvidenceStats, RejectReason } from "./api";
import {
  DROPPED_PANEL_EXPLANATION,
  REJECT_REASONS,
  droppedPanelTitle,
  droppedReasonLabel,
  hasDropped,
  isClean,
  modelCallCount,
  unverifiablePercent,
} from "./evidence";

function stats(overrides: Partial<EvidenceStats> = {}): EvidenceStats {
  return {
    verified: 10,
    dropped: 0,
    total_claims: 10,
    hallucination_rate: 0,
    attempts: 1,
    by_match_kind: {},
    by_reject_reason: {},
    ...overrides,
  };
}

describe("droppedReasonLabel", () => {
  it("has a label for every reason the server can send", () => {
    // The server's `RejectReason` enum, mirrored. A reason with no label renders
    // `undefined` next to a claim, which reads as a bug in the claim rather than in
    // the map — so this is checked here rather than trusted to the type.
    const fromServer: RejectReason[] = ["empty", "too_short", "not_found", "unknown_requirement"];

    expect(REJECT_REASONS.slice().sort()).toEqual(fromServer.slice().sort());
    for (const reason of fromServer) {
      expect(droppedReasonLabel(reason).length).toBeGreaterThan(0);
    }
  });

  it("covers judging's reason, which no extraction can produce", () => {
    // `unknown_requirement` comes only from `pipeline/judge.py`. It lived in a
    // component private to the profile view for two milestones, where the one screen
    // that can produce it had no way to reach it.
    expect(droppedReasonLabel("unknown_requirement")).toContain("requirement");
  });

  it("never says the candidate lacks anything", () => {
    // A dropped claim is a fact about the *model's* output, not about the person.
    // The same refusal as `not_evidenced` — see NOT_EVIDENCED_EXPLANATION.
    const wording = [...REJECT_REASONS.map(droppedReasonLabel), DROPPED_PANEL_EXPLANATION].join(" ");

    for (const forbidden of ["candidate", "lacks", "does not have", "unqualified"]) {
      expect(wording.toLowerCase()).not.toContain(forbidden);
    }
  });
});

describe("isClean", () => {
  it("keys on the dropped count, not on the rounded rate", () => {
    // `hallucination_rate` is rounded to four places on the server
    // (`EvidenceStats.hallucination_rate`), so one dropped claim among enough
    // verified ones rounds to exactly 0.0 — and a rate-based check would then paint
    // the bar green while a fabrication sits in the list below it.
    expect(isClean(stats({ verified: 100_000, dropped: 1, hallucination_rate: 0 }))).toBe(false);
    expect(isClean(stats({ dropped: 0 }))).toBe(true);
  });
});

describe("unverifiablePercent", () => {
  it("reports the stored rate rather than recomputing it", () => {
    expect(unverifiablePercent(stats({ hallucination_rate: 0.0769 }))).toBe("7.7%");
    expect(unverifiablePercent(stats({ hallucination_rate: 0 }))).toBe("0.0%");
    expect(unverifiablePercent(stats({ hallucination_rate: 1 }))).toBe("100.0%");
  });
});

describe("modelCallCount", () => {
  it("counts model calls, which is what `attempts` means on the stats", () => {
    // Deliberately not `Screening.attempts` or `Resume.attempts` — those are the job
    // counters and are incremented by a retry that spent nothing.
    expect(modelCallCount(stats({ attempts: 1 }))).toBe("1 model call");
    expect(modelCallCount(stats({ attempts: 2 }))).toBe("2 model calls");
  });
});

describe("the panel wrapper", () => {
  it("names the count so an empty panel is never rendered as a finding", () => {
    expect(droppedPanelTitle(3)).toContain("(3)");
    expect(hasDropped([])).toBe(false);
    expect(hasDropped(undefined)).toBe(false);
    expect(
      hasDropped([{ field: "skills[0]", value: "Rust", quote: "Rust", reason: "not_found" }]),
    ).toBe(true);
  });
});
