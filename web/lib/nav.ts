/**
 * The application's primary navigation, and the one question it asks.
 *
 * Until now there was no navigation: each screen hand-wrote a header with a single
 * "← back" link and its own Sign out, so where you could go depended on where you
 * happened to be. The links live here rather than in the component so the rule
 * below can be tested without a DOM, which `web/` deliberately does not have.
 *
 * **Every item is shown to every signed-in account, whatever its role.** That is a
 * decision, not an oversight: all four routes answer for all three roles — a
 * candidate browses postings at `/jobs`, a recruiter may apply to one
 * (`api/app/applications.py` says applying is "open to any role"), and `/metrics`
 * scopes its rows in the WHERE clause rather than gating the route. A nav that
 * hid a link the API would happily serve would be the client asserting a rule the
 * server does not have, which is the thing this project refuses everywhere else.
 */
export interface NavItem {
  href: string;
  label: string;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/", label: "Resumes" },
  { href: "/jobs", label: "Jobs" },
  { href: "/applications", label: "Applications" },
  { href: "/metrics", label: "Usage" },
] as const;

/** Drop a trailing slash so `/jobs/` and `/jobs` are the same place. The root is
 *  left alone, since stripping its slash would leave an empty string. */
function normalise(path: string): string {
  return path.length > 1 && path.endsWith("/") ? path.slice(0, -1) : path;
}

/**
 * Is `href` the section the reader is currently in?
 *
 * Two traps, and the naive `pathname.startsWith(href)` walks into both:
 *
 * 1. **`/` is a prefix of everything**, so every screen would light up "Resumes"
 *    as well as its own item.
 * 2. **A prefix is not a path segment.** `/jobs` must not claim `/jobsomething`;
 *    only `/jobs` itself and things under `/jobs/` belong to it. That is what
 *    keeps `/jobs/{id}` marked as Jobs — the reason a prefix test is wanted at
 *    all — without it swallowing an unrelated sibling route later.
 *
 * One line answers both, and there is deliberately **no special case for the
 * root**: comparing against `` `${target}/` `` makes the root's prefix `"//"`, and
 * no normalised path begins with that. An explicit `if (target === "/")` branch was
 * written first and then removed — it changed no result, and this repo deletes a
 * guard that cannot fail. Removing it is what turns the root test below from
 * decoration into the thing that pins trap 1: with the branch present, that test
 * passed even against an implementation that got the root wrong.
 */
export function isActiveNav(pathname: string, href: string): boolean {
  const path = normalise(pathname);
  const target = normalise(href);
  return path === target || path.startsWith(`${target}/`);
}
