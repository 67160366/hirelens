/**
 * Which moves the UI offers, and how the log reads.
 *
 * Not which moves are *allowed* — the server decides that, and duplicating its rules
 * here would create a second place for them to be wrong with the client's copy being
 * the one nobody notices drifting. What is pinned here is the narrower thing this
 * module is for: that the buttons put in front of someone match who they are, and
 * that a blocked one explains itself rather than vanishing.
 */

import { describe, expect, it } from "vitest";

import type { Application, ApplicationEvent, ApplicationState, Role } from "./api";
import {
  availableMoves,
  describeEvent,
  groupByState,
  isTerminal,
  restsOnEvidence,
} from "./applications";

const APPLICANT_ID = "candidate-1";
const OWNER_ID = "recruiter-1";

function application(state: ApplicationState): Application {
  return {
    id: "app-1",
    job_id: "job-1",
    job_title: "Backend Engineer",
    candidate_id: APPLICANT_ID,
    resume_id: "resume-1",
    resume_filename: "cv.pdf",
    state,
    created_at: "2026-08-12T00:00:00Z",
  };
}

function viewer(id: string, role: Role = "candidate") {
  return { id, role };
}

function event(over: Partial<ApplicationEvent>): ApplicationEvent {
  return {
    id: "e1",
    position: 0,
    from_state: null,
    to_state: "applied",
    actor_id: APPLICANT_ID,
    actor_role: "candidate",
    reason: null,
    screening_id: null,
    note: null,
    created_at: "2026-08-12T00:00:00Z",
    ...over,
  };
}

describe("availableMoves", () => {
  it("offers the applicant only their own exit", () => {
    const moves = availableMoves(application("screened"), viewer(APPLICANT_ID), OWNER_ID);
    expect(moves.map((m) => m.to)).toEqual(["withdrawn"]);
  });

  it("offers the job owner shortlist and reject", () => {
    const moves = availableMoves(
      application("screened"),
      viewer(OWNER_ID, "recruiter"),
      OWNER_ID,
    );
    expect(moves.map((m) => m.to)).toEqual(["shortlisted", "rejected"]);
  });

  it("blocks shortlisting before a screening rather than hiding it", () => {
    // A missing button is indistinguishable from a bug. A disabled one that says
    // why is the thing that teaches somebody the rule.
    const moves = availableMoves(
      application("applied"),
      viewer(OWNER_ID, "recruiter"),
      OWNER_ID,
    );
    const shortlist = moves.find((m) => m.to === "shortlisted");
    expect(shortlist).toBeDefined();
    expect(shortlist?.blockedBecause).toContain("cited evidence");
  });

  it("asks for a reason before a rejection, and not before anything else", () => {
    const moves = availableMoves(
      application("screened"),
      viewer(OWNER_ID, "recruiter"),
      OWNER_ID,
    );
    expect(moves.find((m) => m.to === "rejected")?.needsReason).toBe(true);
    expect(moves.find((m) => m.to === "shortlisted")?.needsReason).toBe(false);
  });

  it("treats an admin as the job owner, matching Actor.of on the server", () => {
    const moves = availableMoves(application("screened"), viewer("someone", "admin"), OWNER_ID);
    expect(moves.map((m) => m.to)).toEqual(["shortlisted", "rejected"]);
  });

  it("offers a stranger nothing at all", () => {
    const moves = availableMoves(
      application("screened"),
      viewer("nobody", "recruiter"),
      OWNER_ID,
    );
    expect(moves).toEqual([]);
  });

  it.each(["rejected", "withdrawn"] as const)("offers nothing once %s", (state) => {
    expect(isTerminal(state)).toBe(true);
    expect(availableMoves(application(state), viewer(OWNER_ID, "recruiter"), OWNER_ID)).toEqual(
      [],
    );
  });
});

describe("describeEvent", () => {
  it("says the system moved it when nobody did", () => {
    // Attributing a worker's move to a person would be a small lie in the one
    // place that exists to be accurate about who did what.
    const line = describeEvent(
      event({ actor_id: null, actor_role: null, from_state: "applied", to_state: "screened" }),
    );
    expect(line).toBe("The system moved it to screened");
  });

  it("names the employer for a decision they made", () => {
    const line = describeEvent(
      event({
        actor_id: OWNER_ID,
        actor_role: "recruiter",
        from_state: "screened",
        to_state: "shortlisted",
      }),
    );
    expect(line).toBe("The employer moved it to shortlisted");
  });

  it("reads the first entry as an application rather than a move", () => {
    expect(describeEvent(event({ from_state: null }))).toBe("The candidate applied");
  });
});

describe("restsOnEvidence", () => {
  it("is true only when the entry names a screening", () => {
    expect(restsOnEvidence(event({ screening_id: "s1" }))).toBe(true);
    expect(restsOnEvidence(event({ screening_id: null }))).toBe(false);
  });
});

describe("groupByState", () => {
  it("puts what needs a decision first and drops empty groups", () => {
    const groups = groupByState([
      { ...application("applied"), id: "a" },
      { ...application("shortlisted"), id: "b" },
      { ...application("screened"), id: "c" },
    ]);
    expect(groups.map((g) => g.state)).toEqual(["screened", "shortlisted", "applied"]);
  });
});
