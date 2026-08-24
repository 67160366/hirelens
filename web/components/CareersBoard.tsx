"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Banner } from "@/components/ui/Banner";
import { Card } from "@/components/ui/Card";
import { api, type Posting } from "@/lib/api";
import { errorMessage } from "@/lib/auth";

/** How many of a posting's requirements are hard gates rather than weights. */
function mustHaves(posting: Posting): number {
  return posting.requirements.filter((item) => item.must_have).length;
}

/**
 * The public board: every posting the company has published.
 *
 * **A client component, like every other screen here, and that is what keeps
 * `npm run build` free of the API.** `docs/PLAN.md` repair #4 asks for exactly
 * that, and the usual answer — `export const dynamic = "force-dynamic"` on a
 * server component — is not the one this app needs. Fetching on the server would
 * mean fetching from inside the `web` container, where `NEXT_PUBLIC_API_BASE`
 * (`http://localhost:8000`) points at the container itself and not at the API. So
 * the data is read in the browser, where that origin is correct, and the build
 * touches nothing.
 *
 * **That cost was paid on 2026-08-24 rather than kept.** A posting's title was not
 * in the server-rendered HTML, so a search engine saw an empty board — on the one
 * surface that exists to be found. The page above it is now a server component
 * that fetches through `lib/serverApi` and hands the rows down as
 * `initialPostings`; this component keeps its own fetch for the case where the
 * server could not reach the API, and the build still touches nothing, because
 * that fetch cannot fail a build it never runs in.
 */
export function CareersBoard({ initialPostings }: { initialPostings: Posting[] | null }) {
  // Seeded from the server render, so the list is in the HTML a crawler reads and
  // on screen before hydration. `null` means the server could not reach the API —
  // the fetch below then answers the same question from the browser, where the
  // address is a different one and may well work.
  const [postings, setPostings] = useState<Posting[] | null>(initialPostings);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initialPostings !== null) return;
    api
      .listPostings()
      .then(setPostings)
      .catch((caught) => setError(errorMessage(caught, "โหลดตำแหน่งงานไม่สำเร็จ")));
  }, [initialPostings]);

  return (
    <div className="mx-auto max-w-3xl px-5 py-12">
      <h1 className="text-2xl font-semibold tracking-tight text-ink">ร่วมงานกับเรา</h1>
      <p className="mt-2 max-w-prose text-sm leading-relaxed text-ink-muted">
        แต่ละตำแหน่งบอกไว้ก่อนว่าวัดจากอะไร พอคัดเสร็จ
        คุณเปิดดูผลชุดเดียวกับที่ทีมเราอ่าน
      </p>

      {error && (
        <Banner tone="danger" className="mt-6">
          {error}
        </Banner>
      )}

      {postings === null && !error && (
        <p className="mt-8 text-sm text-ink-muted">กำลังโหลด…</p>
      )}

      {postings?.length === 0 && (
        <p className="mt-8 text-sm text-ink-muted">
          ตอนนี้ยังไม่มีตำแหน่งที่เปิดรับ ไว้แวะมาดูใหม่นะ
        </p>
      )}

      <ul className="mt-8 space-y-3">
        {postings?.map((posting) => (
          <li key={posting.id}>
            <Card>
              <Link
                href={`/careers/${posting.id}`}
                className="ring-focus block px-4 py-3.5 hover:bg-surface-sunken"
              >
                <span className="block text-sm font-medium text-ink">{posting.title}</span>
                <span className="mt-0.5 block text-micro text-ink-faint">
                  {posting.location ?? "ไม่ได้ระบุสถานที่"}
                  {posting.requirements.length > 0 && (
                    <>
                      {" · "}
                      {posting.requirements.length} ข้อที่วัด
                      {mustHaves(posting) > 0 && ` · ต้องมี ${mustHaves(posting)} ข้อ`}
                    </>
                  )}
                </span>
              </Link>
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}
