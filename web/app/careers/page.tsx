import type { Metadata } from "next";

import { CareersBoard } from "@/components/CareersBoard";
import { fetchPostings } from "@/lib/serverApi";

/**
 * The board, rendered on the server so the postings are in the HTML.
 *
 * `force-dynamic` rather than static: the list changes when an administrator
 * publishes something, and `next build` must never need a running API
 * (`docs/PLAN.md` repair #4). `fetchPostings` answers `null` rather than throwing
 * when the API is unreachable, so a build with nothing running still succeeds and
 * the client component below falls back to fetching from the browser.
 */
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "ร่วมงานกับเรา — HireLens",
  description:
    "ตำแหน่งที่ HireLens เปิดรับ แต่ละตำแหน่งบอกไว้ก่อนว่าวัดจากอะไร และผลการคัดเปิดให้ผู้สมัครอ่านได้",
};

export default async function CareersPage() {
  return <CareersBoard initialPostings={await fetchPostings()} />;
}
