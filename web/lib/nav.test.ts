import { describe, expect, it } from "vitest";

import {
  NAV_ITEMS,
  PUBLIC_NAV_ITEMS,
  activeNavHref,
  isActiveNav,
  isPublicRoute,
  navItemsFor,
  scrollLeftToShow,
} from "./nav";

describe("isActiveNav", () => {
  it("marks a section active on its own path", () => {
    expect(isActiveNav("/hire", "/hire")).toBe(true);
  });

  it("marks a section active on a path beneath it, which is why /hire/jobs/{id} says Hire", () => {
    expect(isActiveNav("/hire/jobs/9f3c1d2e", "/hire")).toBe(true);
  });

  // The first trap. `"/hire".startsWith("/")` is true, so a naive prefix test lights
  // the root up on every screen in the app and the reader can never tell where they
  // are. Deleting the `target === "/"` branch fails this and nothing else.
  it("does not mark the root active anywhere but the root", () => {
    expect(isActiveNav("/", "/")).toBe(true);
    expect(isActiveNav("/hire", "/")).toBe(false);
    expect(isActiveNav("/usage", "/")).toBe(false);
  });

  // The second trap, and the reason the test is `startsWith(target + "/")` rather
  // than `startsWith(target)`: a prefix is not a path segment.
  it("does not claim a route that merely starts with the same letters", () => {
    expect(isActiveNav("/hireling", "/hire")).toBe(false);
    expect(isActiveNav("/careers-archive", "/careers")).toBe(false);
  });

  it("treats a trailing slash as the same place", () => {
    expect(isActiveNav("/hire/", "/hire")).toBe(true);
    expect(isActiveNav("/", "/")).toBe(true);
  });

  it("does not mark an unrelated section active", () => {
    expect(isActiveNav("/hire", "/me")).toBe(false);
    expect(isActiveNav("/usage", "/hire")).toBe(false);
  });
});

describe("navItemsFor", () => {
  it("hides the back office from a candidate", () => {
    const hrefs = navItemsFor("candidate").map((item) => item.href);
    expect(hrefs).not.toContain("/hire");
  });

  it.each(["recruiter", "admin"] as const)("shows it to a %s", (role) => {
    expect(navItemsFor(role).map((item) => item.href)).toContain("/hire");
  });

  // The rule this file exists to hold: hide only what the server refuses. Usage
  // takes `CandidateDep` and no role gate — it scopes rows in the WHERE clause, so
  // a candidate reading it sees what their own documents cost. Hiding it would be
  // the client inventing a rule the API does not have.
  it.each(["candidate", "recruiter", "admin"] as const)(
    "shows usage to a %s, because the API does",
    (role) => {
      expect(navItemsFor(role).map((item) => item.href)).toContain("/usage");
    },
  );
});

describe("activeNavHref", () => {
  // The property the reader actually cares about, stated over the real list rather
  // than over an example: wherever you are, exactly one item is lit.
  it.each([
    ["/careers", "/careers"],
    ["/me", "/me"],
    ["/me/documents", "/me/documents"],
    ["/hire", "/hire"],
    ["/hire/jobs/9f3c1d2e", "/hire"],
    ["/usage", "/usage"],
  ])("lights %s as %s", (pathname, expected) => {
    expect(activeNavHref(pathname, NAV_ITEMS)).toBe(expected);
  });

  // The reason this function exists at all. `/me` is a prefix of `/me/documents`,
  // so `isActiveNav` alone lights both and the shell shows two current pages.
  it("gives a nested route to its own item rather than to its parent", () => {
    const lit = NAV_ITEMS.filter((item) => isActiveNav("/me/documents", item.href));
    expect(lit).toHaveLength(2);
    expect(activeNavHref("/me/documents", NAV_ITEMS)).toBe("/me/documents");
  });

  it("lights nothing on a screen that is in no section", () => {
    expect(activeNavHref("/", NAV_ITEMS)).toBeNull();
    expect(activeNavHref("/how-we-screen", NAV_ITEMS)).toBeNull();
  });

  it("lights the public items on the public pages", () => {
    expect(activeNavHref("/careers", PUBLIC_NAV_ITEMS)).toBe("/careers");
    expect(activeNavHref("/careers/9f3c1d2e", PUBLIC_NAV_ITEMS)).toBe("/careers");
    expect(activeNavHref("/", PUBLIC_NAV_ITEMS)).toBeNull();
  });
});

describe("isPublicRoute", () => {
  // The rule this predicate exists for: which shell you get is decided by the
  // route, not by the session. It was the other way round for one commit, and a
  // signed-in applicant reading a job advertisement was shown Documents, Usage and
  // Hire — the back office's bar on the company's front page.
  it.each(["/", "/careers", "/careers/9f3c1d2e", "/how-we-screen", "/demo"])(
    "treats %s as the public site",
    (pathname) => {
      expect(isPublicRoute(pathname)).toBe(true);
    },
  );

  it.each(["/me", "/me/documents", "/hire", "/hire/jobs/9f3c1d2e", "/usage"])(
    "treats %s as the application",
    (pathname) => {
      expect(isPublicRoute(pathname)).toBe(false);
    },
  );

  // A prefix is not a path segment, here as everywhere else in this file.
  it("does not hand the public shell to a route that merely starts the same", () => {
    expect(isPublicRoute("/careers-archive")).toBe(false);
  });

  it("treats a trailing slash as the same place", () => {
    expect(isPublicRoute("/careers/")).toBe(true);
  });
});

/**
 * The narrow bar, and the promise its comment makes.
 *
 * `AppShell`'s strip is `overflow-x-auto` and says the half-visible next item is
 * the affordance. At 375 the public bar hands the strip exactly the width of its
 * first item, so the second is clipped edge to edge — and `/how-we-screen` is the
 * first page that can be the clipped one.
 */
describe("scrollLeftToShow", () => {
  // A 96px strip sitting 90px from the left of the viewport, scrolled to the start.
  const view = { left: 90, scrollLeft: 0, clientWidth: 96 };

  it("leaves a strip alone when the item is already in view", () => {
    expect(scrollLeftToShow({ left: 102, width: 60 }, view)).toBeNull();
  });

  // The case that was on screen: the second public item starts past the right edge.
  it("scrolls right far enough to show an item past the edge", () => {
    expect(scrollLeftToShow({ left: 190, width: 76 }, view)).toBe(92);
  });

  it("scrolls back left for an item behind the current position", () => {
    expect(scrollLeftToShow({ left: 92, width: 60 }, { ...view, scrollLeft: 90 })).toBe(80);
  });

  // Never a negative scrollLeft: an item at the very start with the padding
  // subtracted would ask for one, and the browser would clamp it silently.
  it("never asks for a negative offset", () => {
    expect(scrollLeftToShow({ left: 54, width: 60 }, { ...view, scrollLeft: 40 })).toBe(0);
  });

  it("keeps a margin of the neighbour visible, which is what says the strip scrolls", () => {
    expect(scrollLeftToShow({ left: 190, width: 76 }, view, 0)).toBe(80);
  });

  // The reason the helper takes rects at all: the bar is `position: sticky`, so it
  // is the offset parent and `offsetLeft` measures from the header instead of from
  // the strip. Scrolling the strip must not depend on where the strip sits.
  it("gives the same answer wherever the strip sits on the page", () => {
    const shifted = scrollLeftToShow({ left: 490, width: 76 }, { ...view, left: 390 });
    expect(shifted).toBe(scrollLeftToShow({ left: 190, width: 76 }, view));
  });
});
