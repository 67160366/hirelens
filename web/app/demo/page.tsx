"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { DocumentPane, EvidenceSelectionProvider, spanKey } from "@/components/DocumentPane";
import { DroppedClaims } from "@/components/DroppedClaims";
import { Evidence } from "@/components/Evidence";
import { Badge } from "@/components/ui/Badge";
import { Banner } from "@/components/ui/Banner";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { api, type DemoMode, type DemoScreening, type EvidenceRef } from "@/lib/api";
import { errorMessage } from "@/lib/auth";

/**
 * Every distinct span on the screen, so the document pane can highlight them.
 *
 * Filtered on `met` rather than flat-mapped over everything: the two are the same
 * list today, because a verdict is derived from whether a quote resolved, and
 * saying so here is what keeps the pane honest if that ever moves.
 *
 * **Deduplicated, which the receipt does not do**, because on this document two
 * requirements cite the same skills line. The pane paints overlapping spans once
 * — the earliest and longest wins — so passing both would have printed "3 spans"
 * over two highlights. A count that does not match what is painted is exactly the
 * kind of small dishonesty this page is arguing against.
 */
function citations(demo: DemoScreening): EvidenceRef[] {
  const seen = new Set<string>();
  return demo.requirements
    .filter((requirement) => requirement.verdict === "met")
    .flatMap((requirement) => requirement.evidence)
    .filter((reference) => {
      const key = spanKey(reference);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

const MODES: { value: DemoMode; label: string; hint: string }[] = [
  {
    value: "faithful",
    label: "โมเดลที่ยกข้อความจริง",
    hint: "ทุกข้อความที่ตอบกลับมา คัดลอกมาจากเอกสารจริง",
  },
  {
    value: "fabricating",
    label: "โมเดลที่แต่งข้อความ",
    hint: "แถมข้อความที่ไม่มีอยู่ในเอกสารมาหนึ่งข้อ",
  },
];

/**
 * The demo: the guardrail, run live for somebody with no account.
 *
 * **Everything on this page came back from the API this second.** The verdicts,
 * the offsets and the refusal are produced by `GET /demo/screening`, which runs
 * the real `judge_requirements` and the real `EvidenceResolver` over a committed
 * synthetic document. A screenshot of a refusal would have been cheaper and would
 * have made this the one page in the product asserting something it had not
 * verified — on the page whose whole job is to argue that we do not do that.
 *
 * The toggle is the argument. The same document and the same requirements are
 * judged twice: once by a model that quotes what is there, and once by one that
 * invents a line. The verdicts do not move — that is the point — and the invented
 * line appears under the panel with a rule drawn through it.
 *
 * **No score, no rank, no percentage**, matching `ReceiptOut`: a number that only
 * means something beside other candidates is the one thing a page about a single
 * document must not teach.
 */
export default function DemoPage() {
  const [mode, setMode] = useState<DemoMode>("faithful");

  /**
   * The answer, carrying the mode it is an answer *to*.
   *
   * One object rather than a `demo` and an `error` cleared by an effect: the rule
   * `useAuth`'s rewrite bought is that state which follows something is derived
   * from it, never reset by an effect reacting to it. Clearing on the way into the
   * fetch would also be a frame late — the reader would see the previous model's
   * verdicts under the new model's button until React got round to the effect.
   */
  const [answer, setAnswer] = useState<{
    mode: DemoMode;
    demo?: DemoScreening;
    error?: string;
  } | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getDemo(mode)
      .then((demo) => {
        if (!cancelled) setAnswer({ mode, demo });
      })
      .catch((caught) => {
        if (!cancelled) {
          setAnswer({ mode, error: errorMessage(caught, "เรียกตัวอย่างการคัดไม่สำเร็จ") });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [mode]);

  // Nothing belonging to the other model is ever on screen: the mode it was
  // fetched for has to match the one selected now.
  const current = answer?.mode === mode ? answer : null;
  const demo = current?.demo ?? null;
  const error = current?.error ?? null;

  return (
    <div className="mx-auto max-w-6xl px-5 py-12">
      <header className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
          ลองดูของจริง
        </h1>
        <p className="mt-2 text-sm text-ink-faint" lang="en">
          The same document, judged twice — once by a model that quotes, once by one that invents.
        </p>
        <p className="mt-5 text-base leading-relaxed text-ink-muted">
          ข้างล่างนี้คือประกาศงานหนึ่งใบกับเรซูเม่สมมติหนึ่งฉบับ ทุกครั้งที่คุณสลับปุ่ม
          ระบบคัดใหม่จริง ๆ ไม่ใช่ภาพที่เตรียมไว้ ลองสลับไปโหมดที่โมเดลแต่งข้อความดู
          แล้วดูว่าผลตัดสินขยับหรือเปล่า
        </p>
      </header>

      <div className="mt-8 flex flex-wrap gap-2" role="group" aria-label="เลือกโมเดล">
        {MODES.map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() => setMode(option.value)}
            aria-pressed={mode === option.value}
            className={
              mode === option.value
                ? "btn btn-primary btn-lg"
                : "btn btn-secondary btn-lg ring-focus"
            }
          >
            {option.label}
          </button>
        ))}
        <p className="w-full text-micro text-ink-faint">
          {MODES.find((option) => option.value === mode)?.hint}
        </p>
      </div>

      {error && (
        <Banner tone="danger" className="mt-6">
          {error}
        </Banner>
      )}

      {!demo && !error && <p className="mt-8 text-sm text-ink-muted">กำลังคัด…</p>}

      {demo && (
        <EvidenceSelectionProvider>
          <div className="mt-8 grid gap-4 lg:grid-cols-2 lg:items-start">
            <div className="space-y-4">
              <Card>
                <CardHeader
                  title={demo.posting_title}
                  caption={`วัดจาก ${demo.requirements.length} ข้อ · เอกสาร ${demo.filename}`}
                  action={
                    <span className="text-micro text-ink-faint">
                      อ้างอิงได้ {demo.verified} · ตัดออก {demo.dropped_count}
                    </span>
                  }
                />
                <CardBody padded={false} className="divide-y divide-line">
                  {demo.requirements.map((requirement) => (
                    <div key={requirement.label} className="px-4 py-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium text-ink">{requirement.label}</span>
                        {requirement.must_have && (
                          <Badge tone="neutral" title="ข้อที่ต้องมี ไม่งั้นไม่ผ่านด่านแรก">
                            ต้องมี
                          </Badge>
                        )}
                        <span className="ml-auto">
                          {requirement.verdict === "met" ? (
                            <Badge tone="cited">อ้างอิงได้</Badge>
                          ) : (
                            <Badge tone="neutral">หาหลักฐานไม่เจอ</Badge>
                          )}
                        </span>
                      </div>

                      {requirement.evidence.map((reference, index) => (
                        <Evidence key={index} reference={reference} />
                      ))}

                      {requirement.verdict !== "met" && (
                        // The sentence the whole system is arranged around. It is
                        // not "the candidate does not have this": absence cannot be
                        // quoted, so it is never asserted.
                        <p className="mt-1 text-xs leading-relaxed text-ink-muted">
                          ไม่มีข้อความในเอกสารที่อ้างถึงข้อนี้ได้
                          ซึ่งไม่เหมือนกับการบอกว่าผู้สมัครทำไม่ได้
                        </p>
                      )}
                    </div>
                  ))}
                </CardBody>
              </Card>

              <DroppedClaims dropped={demo.dropped} language="th" />

              {demo.dropped.length === 0 && (
                <p className="text-xs leading-relaxed text-ink-muted">
                  รอบนี้ไม่มีข้อความไหนถูกตัดทิ้ง ทุกข้อที่โมเดลยกมา หาเจอในเอกสารทั้งหมด
                </p>
              )}
            </div>

            <DocumentPane text={demo.document_text} references={citations(demo)} language="th" />
          </div>
        </EvidenceSelectionProvider>
      )}

      <section className="mt-12 max-w-3xl border-t border-line pt-8">
        <h2 className="text-xl font-semibold tracking-tight text-ink">
          สองอย่างที่หน้านี้ไม่ได้ทำให้ดู
        </h2>
        <ul className="mt-3 space-y-2 text-sm leading-relaxed text-ink-muted">
          <li>
            <strong className="font-medium text-ink">คะแนน</strong> — ระบบให้คะแนนเวลาจัดอันดับ
            แต่คะแนนมีความหมายก็ต่อเมื่อเทียบกับผู้สมัครคนอื่น
            หน้าที่พูดถึงเอกสารฉบับเดียวจึงไม่ควรสอนตัวเลขนั้น
          </li>
          <li>
            <strong className="font-medium text-ink">การถามซ้ำ</strong> — ของจริงเวลามีข้อความที่หาไม่เจอ
            ระบบจะถามโมเดลอีกครั้งหนึ่งโดยบอกไปว่าข้อไหนใช้ไม่ได้ ตรงนี้ถามครั้งเดียว
            เพราะโมเดลตัวอย่างตอบเหมือนเดิมทุกครั้ง การถามซ้ำจึงได้ข้อความปลอมอันเดิมกลับมา
          </li>
        </ul>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link href="/careers" className="btn btn-primary btn-lg">
            ดูตำแหน่งที่เปิดรับ
          </Link>
          <Link href="/how-we-screen" className="btn btn-secondary btn-lg">
            อ่านวิธีที่เราคัด
          </Link>
        </div>
      </section>
    </div>
  );
}
