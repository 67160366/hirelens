import type { Posting } from "@/lib/api";

/**
 * Reading the public careers data on the **server**, so a crawler sees a board.
 *
 * ### Why this exists at all
 *
 * Every screen in this app is a client component, which is what keeps
 * `npm run build` free of a running API (`docs/PLAN.md` repair #4). The cost was
 * named when the board shipped and is real: the postings are fetched in an
 * effect, effects do not run during server rendering, and **a search engine sees
 * an empty page** on the one surface that exists to be found.
 *
 * ### Why it needs its own base URL
 *
 * `NEXT_PUBLIC_API_BASE` is inlined into the client bundle at build time and is
 * written from the *browser's* point of view — `http://localhost:8000`. Inside the
 * `web` container that address is the container itself, so a server-side fetch
 * with it reaches nothing. `SERVER_API_BASE` is a **runtime** variable naming the
 * API from the server's point of view (`http://api:8000` in compose), and it falls
 * back to the public one because on a developer's machine, running `npm run dev`,
 * the two really are the same address.
 *
 * ### Why nothing here throws
 *
 * These functions are called from `generateMetadata` and from page bodies, both of
 * which run during `next build`. A build that needs a live API is the thing repair
 * #4 forbids, so an unreachable API yields `null` and the page renders its own
 * empty state — the same one the client fetch already produces when the API is
 * down. **A missing board is a worse page; a failed build is a broken deploy.**
 *
 * The `server-only` package would state that in the type system; a marker import
 * is not worth a dependency here, so the guard below is the statement instead —
 * and it is a better one, because it names the mistake rather than failing to
 * compile in a way that has to be looked up.
 */

/** The API as the server sees it. */
export function serverApiBase(): string {
  if (typeof window !== "undefined") {
    // Reached only by importing this module into a client component. The address
    // it would return is the *server's* view of the API and is meaningless from a
    // browser — a silent wrong-host fetch, which is the hardest kind to see.
    throw new Error("lib/serverApi is server-only; the browser must use lib/api");
  }
  return (
    process.env.SERVER_API_BASE ??
    process.env.NEXT_PUBLIC_API_BASE ??
    "http://localhost:8000"
  );
}

/** Never cached: a posting published a minute ago has to appear. */
const NO_STORE = { cache: "no-store" } as const;

export async function fetchPostings(): Promise<Posting[] | null> {
  try {
    const response = await fetch(`${serverApiBase()}/careers/postings`, NO_STORE);
    if (!response.ok) return null;
    return (await response.json()) as Posting[];
  } catch {
    return null;
  }
}

/**
 * One posting, with the two absences kept apart.
 *
 * **A posting that does not exist and an API that cannot be reached are not the
 * same answer**, and collapsing them produced a soft 404: a draft posting's URL
 * answered **200** with the site's default title, which is the shape search
 * engines are known to punish and readers are known to be confused by. `missing`
 * lets the page answer a real 404; `unreachable` lets it render and have the
 * browser ask again from an address that may well work.
 */
export type PostingLookup =
  | { found: true; posting: Posting }
  | { found: false; reason: "missing" | "unreachable" };

export async function fetchPosting(id: string): Promise<PostingLookup> {
  try {
    const response = await fetch(
      `${serverApiBase()}/careers/postings/${encodeURIComponent(id)}`,
      NO_STORE,
    );
    if (response.status === 404) return { found: false, reason: "missing" };
    if (!response.ok) return { found: false, reason: "unreachable" };
    return { found: true, posting: (await response.json()) as Posting };
  } catch {
    return { found: false, reason: "unreachable" };
  }
}
