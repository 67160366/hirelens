/**
 * Tests for the judgment logic behind the ranking screen.
 *
 * Three things here fail *quietly* when they are wrong, which is why they are
 * pinned rather than eyeballed: a `not_evidenced` requirement leaking a highlight
 * would show an unverified claim as sourced, an excluded screening with no message
 * would look like a candidate who simply is not there, and a screening request that
 * lost the 202/200 distinction would stop telling anyone when it spent money.
 */

import { describe, expect, it } from "vitest";

import type {
  EvidenceRef,
  ExcludedEntry,
  RankedEntry,
  RequirementJudgment,
  ScreeningStatus,
} from "./api";
import {
  NOT_EVIDENCED_EXPLANATION,
  collectJudgmentEvidence,
  countCompletedScreenings,
  exclusionMessage,
  makesScreeningsStale,
  resumeLabel,
  scorePercent,
} from "./screening";

function reference(quote: string, start: number): EvidenceRef {
  return {
    quote,
    char_start: start,
    char_end: start + quote.length,
    page: 1,
    match_kind: "exact",
    is_ambiguous: false,
  };
}

function met(label: string, ...evidence: EvidenceRef[]): RequirementJudgment {
  return {
    requirement_id: label,
    label,
    must_have: false,
    weight: 1,
    verdict: "met",
    evidence,
  };
}

function notEvidenced(label: string): RequirementJudgment {
  return {
    requirement_id: label,
    label,
    must_have: false,
    weight: 1,
    verdict: "not_evidenced",
    evidence: [],
  };
}

function excluded(reason: ExcludedEntry["reason"], status = "completed"): ExcludedEntry {
  return { screening_id: "s1", resume_id: "r1", resume_filename: "cv.pdf", status, reason };
}

describe("collectJudgmentEvidence", () => {
  it("gathers every citation behind a met requirement", () => {
    const first = reference("Python", 10);
    const second = reference("FastAPI", 30);

    expect(collectJudgmentEvidence([met("Backend", first, second)])).toEqual([first, second]);
  });

  it("keeps citations from several requirements, in order", () => {
    const python = reference("Python", 10);
    const thai = reference("ภาษาไทย", 40);

    expect(collectJudgmentEvidence([met("Backend", python), met("Language", thai)])).toEqual([
      python,
      thai,
    ]);
  });

  it("contributes nothing for a requirement with no citable evidence", () => {
    expect(collectJudgmentEvidence([notEvidenced("Kubernetes")])).toEqual([]);
  });

  it("highlights nothing for an unevidenced requirement that still carries spans", () => {
    // The load-bearing case, and the reason this filters on the verdict instead of
    // flattening: the contract says the two agree, but if a payload ever disagreed,
    // flattening would highlight a span behind a verdict that was never reached —
    // an unverified claim shown as sourced, which is the one thing this must not do.
    // Asserting it against a fixture with an empty list would prove nothing.
    const contradictory: RequirementJudgment = {
      ...notEvidenced("Kubernetes"),
      evidence: [reference("Kubernetes", 5)],
    };

    expect(collectJudgmentEvidence([contradictory])).toEqual([]);
  });

  it("keeps the met citations when only some requirements resolved", () => {
    const python = reference("Python", 10);

    expect(
      collectJudgmentEvidence([met("Backend", python), notEvidenced("Kubernetes")]),
    ).toEqual([python]);
  });
});

describe("makesScreeningsStale", () => {
  it("is true for what the judge was shown", () => {
    expect(makesScreeningsStale({ label: "Python 3" })).toBe(true);
    expect(makesScreeningsStale({ detail: "at least two years" })).toBe(true);
    expect(makesScreeningsStale({ kind: "experience" })).toBe(true);
  });

  it("is false for the fields ranking reads", () => {
    // `must_have` and `weight` are excluded from the requirements fingerprint on
    // purpose, so editing one reorders the list without re-billing a screening.
    // If this ever flips, every weight nudge starts costing a model call per resume.
    expect(makesScreeningsStale({ weight: 20 })).toBe(false);
    expect(makesScreeningsStale({ must_have: true })).toBe(false);
    expect(makesScreeningsStale({ weight: 3, must_have: false })).toBe(false);
  });

  it("is false for no change at all", () => {
    expect(makesScreeningsStale({})).toBe(false);
  });

  it("is true when a free edit is bundled with a stalening one", () => {
    expect(makesScreeningsStale({ weight: 5, label: "Python 3" })).toBe(true);
  });

  it("treats clearing detail as a change, not as an absent field", () => {
    // `detail: null` clears it, which is a different question for the judge than
    // leaving it alone — `in` is what separates the two, not truthiness.
    expect(makesScreeningsStale({ detail: null })).toBe(true);
  });
});

describe("exclusionMessage", () => {
  it("explains a stale screening without hiding it", () => {
    const message = exclusionMessage(excluded("stale"));
    expect(message).toContain("requirements changed");
    expect(message).toContain("again");
  });

  it("says which unfinished state a screening is in", () => {
    expect(exclusionMessage(excluded("not_completed", "pending"))).toContain("Queued");
    expect(exclusionMessage(excluded("not_completed", "processing"))).toContain("judged");
    expect(exclusionMessage(excluded("not_completed", "dead_lettered"))).toContain("retrying");
  });

  it("falls back to naming the status for one it does not know", () => {
    expect(exclusionMessage(excluded("not_completed", "surprising"))).toContain("surprising");
  });

  it("says a malformed result was left out rather than mis-joined", () => {
    expect(exclusionMessage(excluded("malformed"))).toContain("current requirements");
  });
});

describe("the wording of an unevidenced requirement", () => {
  it("never claims the candidate lacks anything", () => {
    // The `not_met` refusal reaching the screen. The system cannot tell "the
    // candidate lacks it" from "the resume does not mention it", and one of those
    // is a statement about a person — see docs/HANDOFF.md §5.
    expect(NOT_EVIDENCED_EXPLANATION).not.toMatch(/does not have|lacks|missing/i);
    expect(NOT_EVIDENCED_EXPLANATION).toContain("not the same as");
  });
});

describe("scorePercent", () => {
  it("renders a weighted share as a percentage", () => {
    const entry = {
      rank: 1,
      screening_id: "s1",
      resume_id: "r1",
      resume_filename: "cv.pdf",
      gate_passed: true,
      score: 0.6,
      must_haves_met: 2,
      must_haves_total: 2,
      requirements_met: 3,
      requirements_total: 5,
      requirements: [],
    };

    expect(scorePercent(entry)).toBe("60.0%");
    expect(scorePercent({ ...entry, score: 0.9167 })).toBe("91.7%");
  });
});

describe("resumeLabel", () => {
  const entry: RankedEntry = {
    rank: 1,
    screening_id: "s1",
    resume_id: "1234567890abcdef",
    resume_filename: "somchai-cv.pdf",
    gate_passed: true,
    score: 1,
    must_haves_met: 1,
    must_haves_total: 1,
    requirements_met: 1,
    requirements_total: 1,
    requirements: [],
  };

  it("uses the name the server served", () => {
    expect(resumeLabel(entry)).toBe("somchai-cv.pdf");
  });

  it("shortens the id when there is no name, rather than inventing one", () => {
    // Deliberately not a plausible filename: `canRenderOriginal` must go on
    // declining the original-document tab for it, and a reader must be able to see
    // at a glance that this is an id and not what the applicant called their file.
    expect(resumeLabel({ ...entry, resume_filename: null })).toBe("12345678");
  });

  it("answers for an excluded entry too, which carries the same field", () => {
    expect(resumeLabel(excluded("stale"))).toBe("cv.pdf");
  });
});

describe("countCompletedScreenings", () => {
  const at = (status: ScreeningStatus) => ({ status });

  it("counts only the screenings that actually hold a result", () => {
    expect(
      countCompletedScreenings([
        at("completed"),
        at("pending"),
        at("processing"),
        at("failed"),
        at("dead_lettered"),
        at("completed"),
      ]),
    ).toBe(2);
  });

  it("is zero when nothing has completed, rather than the length of the list", () => {
    // The defect this replaces: `screenings.length` would have promised three
    // model calls for a delete that costs none.
    expect(countCompletedScreenings([at("pending"), at("processing"), at("failed")])).toBe(0);
  });

  it("counts nothing on an empty list", () => {
    expect(countCompletedScreenings([])).toBe(0);
  });
});
