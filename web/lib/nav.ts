import type { Role } from "@/lib/api";

/**
 * The application's primary navigation, and the one question it asks.
 *
 * Until the shell existed there was no navigation at all: each screen hand-wrote a
 * header with a single "← back" link and its own Sign out, so where you could go
 * depended on where you happened to be. The links live here rather than in the
 * component so the rules below can be tested without a DOM, which `web/`
 * deliberately does not have.
 *
 * **The rule has not changed; its answer has.** It used to read: every item is
 * shown to every signed-in account, *because* all four routes answered for all
 * three roles, and a nav that hid a link the API would happily serve would be the
 * client asserting a rule the server does not have. That is still the rule, and it
 * is why `role` appears here now — the careers site put the back office behind
 * `require_role`, so `/hire` really is a 403 for a candidate and hiding it is the
 * client agreeing with the server rather than inventing a rule of its own.
 *
 * **`/usage` is the case that keeps the rule honest.** It sits outside `/hire`, and
 * it is shown to everybody, because `GET /metrics/usage` takes `CandidateDep` and
 * no role gate: it scopes rows in the WHERE clause, so a candidate reading it sees
 * what their own documents cost. Filing it under `/hire` and hiding it would have
 * been the exact mistake this docstring exists to prevent, and the path was chosen
 * to stop that from being tempting.
 */
export interface NavItem {
  href: string;
  label: string;
  /** Roles that may reach it, or `undefined` for everybody who is signed in. */
  roles?: readonly Role[];
}

export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/careers", label: "Careers" },
  { href: "/me", label: "Applications" },
  { href: "/me/documents", label: "Documents" },
  { href: "/hire", label: "Hire", roles: ["recruiter", "admin"] },
  { href: "/usage", label: "Usage" },
] as const;

/**
 * What somebody with no session is offered.
 *
 * Not a filtered `NAV_ITEMS`: every signed-in item answers with the sign-in panel
 * until there is a session, so offering them would be four links to one form. The
 * public site is a different set of places, not a subset of the app's.
 */
export const PUBLIC_NAV_ITEMS: readonly NavItem[] = [
  { href: "/careers", label: "ร่วมงานกับเรา" },
  { href: "/how-we-screen", label: "เราคัดกรองอย่างไร" },
] as const;

/** The items an account of this role may reach. */
export function navItemsFor(role: Role): readonly NavItem[] {
  return NAV_ITEMS.filter((item) => item.roles === undefined || item.roles.includes(role));
}

/** Drop a trailing slash so `/hire/` and `/hire` are the same place. The root is
 *  left alone, since stripping its slash would leave an empty string. */
function normalise(path: string): string {
  return path.length > 1 && path.endsWith("/") ? path.slice(0, -1) : path;
}

/**
 * Is `href` the section the reader is currently in?
 *
 * Two traps, and the naive `pathname.startsWith(href)` walks into both:
 *
 * 1. **`/` is a prefix of everything**, so every screen would light up the root as
 *    well as its own item.
 * 2. **A prefix is not a path segment.** `/hire` must not claim `/hireling`; only
 *    `/hire` itself and things under `/hire/` belong to it. That is what keeps
 *    `/hire/jobs/{id}` marked as Hire — the reason a prefix test is wanted at
 *    all — without it swallowing an unrelated sibling route later.
 *
 * One line answers both, and there is deliberately **no special case for the
 * root**: comparing against `` `${target}/` `` makes the root's prefix `"//"`, and
 * no normalised path begins with that. An explicit `if (target === "/")` branch was
 * written first and then removed — it changed no result, and this repo deletes a
 * guard that cannot fail.
 *
 * **`/me` and `/me/documents` are both real items, and the deeper one wins.**
 * `isActiveNav` alone lights both on `/me/documents`, which is what `activeNavHref`
 * below is for: it is the one place that decides, so the shell cannot light two.
 */
export function isActiveNav(pathname: string, href: string): boolean {
  const path = normalise(pathname);
  const target = normalise(href);
  return path === target || path.startsWith(`${target}/`);
}

/**
 * Which single item is lit, out of the ones this reader can see.
 *
 * The longest match, so a nested route belongs to its own item rather than to its
 * parent's. Returns `null` on a screen that is in no section — the landing page is
 * one, and lighting nothing there is more honest than lighting the first thing.
 */
export function activeNavHref(pathname: string, items: readonly NavItem[]): string | null {
  let best: string | null = null;
  for (const item of items) {
    if (isActiveNav(pathname, item.href) && (best === null || item.href.length > best.length)) {
      best = item.href;
    }
  }
  return best;
}
