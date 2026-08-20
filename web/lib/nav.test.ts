import { describe, expect, it } from "vitest";

import { NAV_ITEMS, isActiveNav } from "./nav";

describe("isActiveNav", () => {
  it("marks a section active on its own path", () => {
    expect(isActiveNav("/jobs", "/jobs")).toBe(true);
  });

  it("marks a section active on a path beneath it, which is why /jobs/{id} says Jobs", () => {
    expect(isActiveNav("/jobs/9f3c1d2e", "/jobs")).toBe(true);
  });

  // The first trap. `"/jobs".startsWith("/")` is true, so a naive prefix test lights
  // the root up on every screen in the app and the reader can never tell where they
  // are. Deleting the `target === "/"` branch fails this and nothing else.
  it("does not mark the root active anywhere but the root", () => {
    expect(isActiveNav("/", "/")).toBe(true);
    expect(isActiveNav("/jobs", "/")).toBe(false);
    expect(isActiveNav("/metrics", "/")).toBe(false);
  });

  // The second trap, and the reason the test is `startsWith(target + "/")` rather
  // than `startsWith(target)`: a prefix is not a path segment.
  it("does not claim a route that merely starts with the same letters", () => {
    expect(isActiveNav("/jobsomething", "/jobs")).toBe(false);
    expect(isActiveNav("/applications-archive", "/applications")).toBe(false);
  });

  it("treats a trailing slash as the same place", () => {
    expect(isActiveNav("/jobs/", "/jobs")).toBe(true);
    expect(isActiveNav("/", "/")).toBe(true);
  });

  it("does not mark an unrelated section active", () => {
    expect(isActiveNav("/jobs", "/applications")).toBe(false);
    expect(isActiveNav("/metrics", "/jobs")).toBe(false);
  });

  it("marks every navigation item active on its own href", () => {
    for (const item of NAV_ITEMS) {
      expect(isActiveNav(item.href, item.href)).toBe(true);
    }
  });

  // The property the reader actually cares about, stated over the real list rather
  // than over an example: wherever you are, exactly one item is lit.
  it.each(["/", "/jobs", "/jobs/9f3c1d2e", "/applications", "/metrics"])(
    "lights exactly one item on %s",
    (pathname) => {
      const active = NAV_ITEMS.filter((item) => isActiveNav(pathname, item.href));
      expect(active).toHaveLength(1);
    },
  );
});
