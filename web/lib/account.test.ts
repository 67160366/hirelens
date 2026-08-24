import { describe, expect, it } from "vitest";

import { PASSWORD_CHANGE_NOTICE, erasureConsequences, exportFilename } from "./account";

describe("erasureConsequences", () => {
  it("tells everybody that files go before rows", () => {
    for (const role of ["candidate", "recruiter", "admin"] as const) {
      expect(erasureConsequences(role)[0]).toMatch(/deleted from storage first/);
    }
  });

  // The sentence that is not about the person pressing the button. A recruiter's
  // postings take every screening and every applicant's history with them, and
  // somebody who has not been told that cannot have consented to it.
  it("warns a recruiter that other people's history goes too", () => {
    const said = erasureConsequences("recruiter").join(" ");
    expect(said).toMatch(/other person's application/);
  });

  it("warns an admin as well, since the same rows hang off their postings", () => {
    expect(erasureConsequences("admin")).toHaveLength(erasureConsequences("recruiter").length);
  });

  it("does not tell a candidate about postings they cannot have", () => {
    expect(erasureConsequences("candidate").join(" ")).not.toMatch(/posting/);
    expect(erasureConsequences("candidate")).toHaveLength(2);
  });
});

describe("PASSWORD_CHANGE_NOTICE", () => {
  // Both halves, because either alone misleads: "signs you out everywhere" reads
  // as "you are about to be signed out here too", and the reassurance alone hides
  // what the epoch actually does.
  it("says other devices end and this one does not", () => {
    expect(PASSWORD_CHANGE_NOTICE).toMatch(/everywhere else/);
    expect(PASSWORD_CHANGE_NOTICE).toMatch(/stays signed in/);
  });
});

describe("exportFilename", () => {
  it("names the file after the account id", () => {
    expect(exportFilename("9f3c1d2e-1111-2222-3333-444455556666")).toBe(
      "hirelens-export-9f3c1d2e-1111-2222-3333-444455556666.json",
    );
  });

  // A filename reaches screenshots and support threads, so anything that is not a
  // plain id is dropped rather than escaped — including a path separator, which
  // would otherwise be a download landing somewhere nobody chose.
  it("keeps anything unexpected out of the name", () => {
    expect(exportFilename("../../etc/passwd")).toBe("hirelens-export-etcpasswd.json");
    expect(exportFilename("me@example.com")).toBe("hirelens-export-meexamplecom.json");
  });

  it("still produces a name when the id is empty", () => {
    expect(exportFilename("")).toBe("hirelens-export-account.json");
  });
});
