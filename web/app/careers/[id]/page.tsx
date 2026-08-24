import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { PostingScreen } from "@/components/PostingScreen";
import { fetchPosting } from "@/lib/serverApi";
import { postingMetadata } from "@/lib/postingMeta";

/**
 * One posting, fetched on the server so its title is the page's title.
 *
 * **A shared link used to say "HireLens — explainable resume screening"** and
 * carry no description, because the advertisement arrived after hydration and
 * metadata is decided before it. That is the half of a careers site that travels:
 * a posting is passed around in chat windows and search results long before
 * anybody opens the board.
 *
 * `force-dynamic`, and `fetchPosting` answers `null` instead of throwing, for the
 * same reason as the board: `next build` may not need a running API
 * (`docs/PLAN.md` repair #4). A posting that cannot be fetched here still renders
 * — the client component asks again from the browser.
 */
export const dynamic = "force-dynamic";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  const lookup = await fetchPosting(id);
  return postingMetadata(lookup.found ? lookup.posting : null);
}

export default async function PostingPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const lookup = await fetchPosting(id);
  // A posting that does not exist answers a real 404, rather than 200 with a
  // spinner. A draft's URL did the latter until this — a soft 404, and one that
  // told a crawler the page was fine. An unreachable API is a different absence
  // and falls through: the screen renders and asks again from the browser.
  if (!lookup.found && lookup.reason === "missing") notFound();
  return <PostingScreen initialPosting={lookup.found ? lookup.posting : null} />;
}
