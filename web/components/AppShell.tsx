"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useRef, type ReactNode } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ThemeControl } from "@/components/ThemeControl";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import {
  PUBLIC_NAV_ITEMS,
  activeNavHref,
  isPublicRoute,
  navItemsFor,
  scrollLeftToShow,
  type NavItem,
} from "@/lib/nav";

/**
 * The frame every screen sits in — and there are two of them.
 *
 * Before this there was no shell at all: `layout.tsx` was `<body>{children}</body>`
 * and each screen hand-wrote a header carrying one "← back" link and its own Sign
 * out. So where you could go depended on where you already were, the same control
 * was written five times in four shapes, and the only route to the dashboard was a
 * link on the home page.
 *
 * **Which header you get is decided by the route, not by the session.** That was
 * the other way round for one commit, and it was wrong in a way worth recording:
 * a signed-in applicant reading a job advertisement was shown a bar offering
 * Documents, Usage and — if they happened to be a recruiter — Hire. The company's
 * public site quietly became the back office's front page, for exactly the
 * audience it exists to reassure. Being signed in now changes one thing out here:
 * the sign-in link becomes a link to your own applications.
 *
 * **The bar is opaque on purpose.** A translucent, blurred sticky header is the
 * house style everywhere right now, and `docs/DESIGN.md` §6 refuses glassmorphism.
 * Elevation here is a border and a shadow — depth you can read, not a material
 * effect. §6's relaxation on 2026-08-22 covers the landing page's own background;
 * it does not reach the chrome, which is shared with the product screens.
 *
 * **The active item is tinted `accent`, never `cited`.** Being on a page is a
 * control state, and §1 reserves the three meaning colours for what the system says
 * about a document. Measured rather than assumed, and re-measured when the accent
 * became azure on 2026-08-22: accent on accent-wash is **5.17:1** on paper and
 * **6.89:1** in the dark theme — the tightest pairing this file introduces, and
 * still clear of the 4.5:1 floor. The dark half used to be the tight one at 4.98
 * and is now the comfortable one.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const { session, ready, signOut } = useAuth();
  const pathname = usePathname();
  const isPublic = isPublicRoute(pathname);

  // Memoised so the effect below has a dependency that changes when the *set* of
  // links changes and not on every render — `navItemsFor` builds a new array each
  // call, and an effect that writes `scrollLeft` on every render would fight a
  // reader who had scrolled the strip by hand.
  const role = session?.role ?? null;
  const items: readonly NavItem[] = useMemo(
    () => (isPublic ? PUBLIC_NAV_ITEMS : role ? navItemsFor(role) : []),
    [isPublic, role],
  );
  // One place decides, so the bar can never light two items — `/me` is a prefix of
  // `/me/documents`, and `isActiveNav` alone is true for both.
  const active = activeNavHref(pathname, items);

  // Keep the lit item in view on a narrow bar. At 375 the strip is only as wide as
  // one item, so a reader on the second one saw a bar with nothing lit in it and no
  // sign that anything had been scrolled away. The strip's own `scrollLeft` is
  // written, never the page's — `scrollIntoView` would move the document too.
  //
  // **It is re-run from a `ResizeObserver` rather than only on mount**, and that is
  // not defensive: the Thai webfont arrives *after* the effect first runs, so the
  // items are still narrow enough to fit, the strip reports nothing to scroll, and
  // the adjustment that would have been needed a frame later never happens. Watched
  // doing exactly that — the item was clipped on screen while the code was correct.
  //
  // `ready` is in the dependency list because the bar does not exist until it is
  // true — the whole header is gated on it — and on a public route `items` and
  // `active` are the same values before and after, so without it the effect ran
  // once against a `null` ref and never again.
  const strip = useRef<HTMLElement>(null);
  useEffect(() => {
    const view = strip.current;
    if (!view) return;

    function adjust() {
      // Found by attribute rather than through a ref on the `<Link>`: the lit item
      // is already marked `aria-current="page"` for a screen reader, and reusing
      // that keeps one source of truth for which item is lit rather than two that
      // can disagree.
      const item = view!.querySelector<HTMLElement>('[aria-current="page"]');
      if (!item) return;
      const box = item.getBoundingClientRect();
      const target = scrollLeftToShow(
        { left: box.left, width: box.width },
        {
          left: view!.getBoundingClientRect().left,
          scrollLeft: view!.scrollLeft,
          clientWidth: view!.clientWidth,
        },
      );
      if (target !== null) view!.scrollLeft = target;
    }

    adjust();
    const observer = new ResizeObserver(adjust);
    // The strip, because the window can be resized; the lit item, because a webfont
    // changes its width without changing the strip's.
    observer.observe(view);
    const item = view.querySelector('[aria-current="page"]');
    if (item) observer.observe(item);
    return () => observer.disconnect();
  }, [active, items, ready]);

  return (
    <div className="flex min-h-screen flex-col">
      {/* First thing in the tab order, and invisible until it has focus. Without it
          the only way past the navigation is to tab through every link on every
          page — WCAG 2.4.1, and a floor `docs/DESIGN.md` §5 states. */}
      <a href="#main-content" className="skip-link">
        Skip to content
      </a>

      <header className="sticky top-0 z-30 border-b border-line bg-surface shadow-card">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-4 px-5">
          <Link
            href="/"
            className="ring-focus shrink-0 rounded-control text-sm font-semibold tracking-tight text-ink"
          >
            HireLens
          </Link>

          {ready ? (
            <>
              {/* Scrolls rather than wraps at 375px — a navigation that reflows onto
                  two lines pushes the page content below the fold on a phone. The bar
                  itself is hidden because it eats a sixth of a 56px header and reads
                  as a rendering fault; the half-visible next item is the affordance,
                  and it is the one a reader acts on anyway. */}
              <nav
                ref={strip}
                aria-label="Primary"
                className="no-scrollbar -mx-1 flex-1 overflow-x-auto px-1"
              >
                <ul className="flex items-center gap-1">
                  {items.map((item) => (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        aria-current={active === item.href ? "page" : undefined}
                        className={cn(
                          "ring-focus block whitespace-nowrap rounded-control px-2.5 py-1.5 text-xs font-medium transition-colors",
                          active === item.href
                            ? "bg-accent-wash text-accent"
                            : "text-ink-muted hover:bg-surface-sunken hover:text-ink",
                        )}
                      >
                        {item.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </nav>

              <div className="flex shrink-0 items-center gap-2.5">
                {isPublic ? (
                  // The public bar carries no identity and no sign-out. Who you are
                  // is the application's business; out here the only question is
                  // whether there is somewhere of yours to go back to.
                  <Link
                    href="/me"
                    className="ring-focus whitespace-nowrap rounded-control px-2.5 py-1.5 text-xs font-medium text-ink-muted hover:bg-surface-sunken hover:text-ink"
                  >
                    {session ? "ใบสมัครของฉัน" : "เข้าสู่ระบบ"}
                  </Link>
                ) : session ? (
                  <>
                    {/* Who you are is also the way to your account, which is how
                        `/me/account` is reached without a sixth item in a bar that
                        already does not fit at 375. The email is the first thing to
                        go when the bar is narrow: the role is the part that explains
                        why a screen refuses something, and it is two words rather
                        than an address — so the link keeps a target at every width. */}
                    <Link
                      href="/me/account"
                      aria-label="Account"
                      className="ring-focus flex items-center gap-2 rounded-control px-1 py-0.5 hover:bg-surface-sunken"
                    >
                      <span className="hidden max-w-[16ch] truncate text-xs text-ink-muted md:inline">
                        {session.email}
                      </span>
                      <Badge tone="neutral">{session.role}</Badge>
                    </Link>
                    <Button variant="ghost" onClick={() => void signOut()}>
                      Sign out
                    </Button>
                  </>
                ) : null}
              </div>
            </>
          ) : (
            <span className="flex-1" />
          )}

          {/* Outside every branch on purpose: the sign-in form is a screen too, and
              it has to be readable — and checkable — in both themes by somebody who
              has no session yet. */}
          <ThemeControl />
        </div>
      </header>

      {/* The landmark lives here and the measure lives on the page, because the
          screens genuinely want different widths — the workbench needs 6xl and an
          application list reads badly wider than 3xl.

          `tabIndex={-1}` is what makes the skip link do its job. `<main>` is not
          focusable on its own, so following the fragment moved the *scroll* and left
          focus where it was — the next Tab went straight back into the navigation the
          reader had just asked to skip. Chrome papers over this with a sequential
          focus starting point; not every engine does, and a skip link that works in
          one browser is not one. */}
      <main id="main-content" tabIndex={-1} className="flex-1 focus:outline-none">
        {children}
      </main>

      {/* A footer on the public site only. On a product screen it would be one more
          thing between the reader and the row they came for. */}
      {isPublic && (
        <footer className="border-t border-line bg-surface">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-5 py-6">
            <p className="text-micro text-ink-faint">
              HireLens · คัดเรซูเม่แบบที่ชี้ได้ว่าอ่านมาจากบรรทัดไหน
            </p>
            <nav aria-label="Footer" className="flex items-center gap-4">
              {PUBLIC_NAV_ITEMS.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="ring-focus rounded-control text-micro text-ink-muted hover:text-ink"
                >
                  {item.label}
                </Link>
              ))}
              <Link
                href="/me"
                className="ring-focus rounded-control text-micro text-ink-muted hover:text-ink"
              >
                ใบสมัครของฉัน
              </Link>
            </nav>
          </div>
        </footer>
      )}
    </div>
  );
}
