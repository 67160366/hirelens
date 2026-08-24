"use client";

import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { useScrollReveal } from "@/lib/reveal";
import {
  SAMPLE_DOCUMENT,
  SAMPLE_FABRICATION,
  SAMPLE_QUOTE,
  splitAroundQuote,
} from "@/lib/sample";

/** The three steps, in the order the pipeline actually runs them. */
const STEPS = [
  {
    title: "โมเดลตอบมาได้อย่างเดียว คือข้อความที่ยกมาจากเอกสาร",
    body: "เราไม่ได้ถามโมเดลว่าคุณผ่านหรือไม่ผ่าน เราถามว่า “ข้อความตรงไหนในเอกสารที่บอกว่าตรงกับสิ่งที่ประกาศรับ” แล้วให้ตอบกลับมาเป็นข้อความล้วน ๆ ไม่มีคำตัดสิน ไม่มีเลขหน้า ไม่มีเลขตัวอักษร",
  },
  {
    title: "โปรแกรมเป็นฝ่ายหาเองว่าข้อความนั้นอยู่ตรงไหน",
    body: "ระบบเอาข้อความที่ได้ไปค้นในไฟล์ที่คุณอัปโหลดจริง ๆ เจอเมื่อไหร่ถึงจะรู้ตำแหน่งตัวอักษร และตำแหน่งนั้นก็คือสิ่งที่เอาไปไฮไลต์ให้คุณดูทีหลัง",
  },
  {
    title: "ข้อไหนหาไม่เจอ เราตัดทิ้งตั้งแต่ต้น แล้วบอกว่าตัดไปกี่ข้อ",
    body: "ถ้าค้นทั้งเอกสารแล้วไม่มีข้อความนั้น แปลว่าโมเดลแต่งขึ้นมา เราไม่ส่งต่อให้ใครอ่าน ไม่เอาไปคิดคะแนน และนับไว้เป็นตัวเลขของระบบเองว่าเดือนนี้แต่งไปกี่ครั้ง",
  },
] as const;

/** What the system refuses to do, worded as decisions rather than as gaps. */
const REFUSALS = [
  {
    title: "ไม่ให้โมเดลบอกตำแหน่งเอง",
    body: "โมเดลนับตัวอักษรไม่แม่น เราจึงไม่เคยถาม ตำแหน่งทุกตัวเลขที่คุณเห็นมาจากการค้นในไฟล์ ไม่ได้มาจากคำตอบของโมเดล",
  },
  {
    title: "ไม่มีคำว่า “ไม่มีคุณสมบัติ”",
    body: "ผลมีสองแบบคือ “อ้างอิงได้” กับ “หาหลักฐานในเอกสารไม่เจอ” สองอย่างนี้ไม่เหมือนกัน อย่างหลังแปลว่าเอกสารไม่ได้เขียนไว้ ไม่ได้แปลว่าคุณทำไม่ได้",
  },
  {
    title: "ไม่โชว์คะแนนในใบสรุปของผู้สมัคร",
    body: "คะแนนเป็นการเทียบกับผู้สมัครคนอื่น พอเอามาโชว์เดี่ยว ๆ มันชวนให้ถามว่า “ทำไมได้ 62%” ซึ่งเป็นคำถามที่เราตอบตรง ๆ ไม่ได้ สิ่งที่เราตอบได้คือทีละข้อว่าอ่านเจอที่บรรทัดไหน",
  },
  {
    title: "ไม่เอาตัวเลขอัตราการแต่งข้อความมาโฆษณา",
    body: "เราวัดมันทุกครั้งและใช้มันจริง แต่มันวัดจากชุดเอกสารสังเคราะห์ของเราเอง การเอาไปประกาศเหมือนว่ามันคือผลจากเรซูเม่ของคนจริงเป็นคนละเรื่องกัน",
  },
] as const;

/**
 * The public explainer: what happens to a document after it is uploaded.
 *
 * **The page the header has been linking to since the careers site landed.**
 * `web/lib/nav.ts` offers it on every public page and the landing page's second
 * call to action points at it; until this file existed both were a 404.
 *
 * ### Why the illustration is drawn rather than described
 *
 * `docs/DESIGN.md` §6 relaxed for the marketing surface on 2026-08-22, and the
 * half that did **not** relax is that motion has to show the mechanism. So the
 * example below runs the two motions the product itself runs: Motion 1 paints a
 * located quote in from the left, and Motion 2 *draws* the strike through a quote
 * that was not found. A strike that is simply there is a styling choice; watching
 * the refusal happen is the argument.
 *
 * Two things it deliberately does not do:
 *
 * - **It does not locate anything.** The highlight sits on `SAMPLE_QUOTE` because
 *   `splitAroundQuote` found it in `SAMPLE_DOCUMENT`, and no character offsets are
 *   printed. Offsets belong to `api/app/pipeline/evidence.py`, which is the only
 *   thing in this system allowed to say where a quote sits — a second locator on a
 *   marketing page would be a second chance to get it wrong.
 * - **It states no measured number.** §6's last bullet stands in full: no
 *   hallucination rate, no customer count, no logo wall.
 *
 * The replay button exists because the illustration sits below the fold on a
 * phone, and an animation that played while the reader was still at the top is an
 * animation nobody saw. It remounts the block by key rather than re-triggering the
 * animation by hand, which is also how the reader can watch it as many times as
 * they like. Under `prefers-reduced-motion` the CSS neutralises both motions and
 * the resting state — highlight painted, line struck — is already the finished
 * picture.
 */
export default function HowWeScreenPage() {
  useScrollReveal();
  const [take, setTake] = useState(0);

  return (
    <div className="mx-auto max-w-3xl px-5 py-12">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
          เราอ่านเรซูเม่ของคุณยังไง
        </h1>
        <p className="mt-2 text-sm text-ink-faint" lang="en">
          How we screen — and the three things we refuse to do.
        </p>
        <p className="mt-5 max-w-prose text-base leading-relaxed text-ink-muted">
          ระบบคัดเรซูเม่ส่วนใหญ่ตอบได้แค่ผ่านหรือไม่ผ่าน แล้วจบตรงนั้น
          ของเราตั้งกติกาไว้ข้อเดียวตั้งแต่วันแรก คือทุกอย่างที่ระบบพูดถึงคุณ
          ต้องชี้กลับไปที่ข้อความในเอกสารของคุณได้ ชี้ไม่ได้ก็ไม่พูดถึงเลย
        </p>
      </header>

      <section className="mt-12">
        <h2 data-reveal className="text-xl font-semibold tracking-tight text-ink">
          สามขั้น
        </h2>
        <ol className="mt-6 space-y-3">
          {STEPS.map((step, index) => (
            <li key={step.title} data-reveal style={{ animationDelay: `${index * 90}ms` }}>
              <Card>
                <CardBody className="flex gap-4 px-4 py-4">
                  <span className="font-mono text-micro tabular-nums text-accent">
                    0{index + 1}
                  </span>
                  <div className="min-w-0">
                    <h3 className="text-sm font-semibold text-ink">{step.title}</h3>
                    <p className="mt-1.5 text-sm leading-relaxed text-ink-muted">{step.body}</p>
                  </div>
                </CardBody>
              </Card>
            </li>
          ))}
        </ol>
      </section>

      <section className="mt-14">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 data-reveal className="text-xl font-semibold tracking-tight text-ink">
              ขั้นที่สามหน้าตาเป็นแบบนี้
            </h2>
            <p data-reveal className="mt-1.5 max-w-prose text-sm text-ink-muted">
              เอกสารตัวอย่างข้างล่างเป็นของสมมติที่เราเขียนขึ้นเอง โมเดลยกมาสองข้อ
              ข้อหนึ่งอยู่ในเอกสารจริง อีกข้อไม่มีอยู่ ภาพนี้นิ่ง ๆ ถ้าอยากเห็นระบบคัดสด ๆ{" "}
              <Link href="/demo" className="text-accent underline underline-offset-2">
                กดดูที่หน้าตัวอย่าง
              </Link>
            </p>
          </div>
          {/* Not the `Button` primitive: this is a replay control for the example,
              and giving it a filled or outlined button's weight would make it
              compete with the two calls to action at the bottom of the page. */}
          <button
            type="button"
            onClick={() => setTake((current) => current + 1)}
            className="btn btn-ghost ring-focus shrink-0"
          >
            เล่นอีกครั้ง
          </button>
        </div>

        <div key={take} className="mt-6 grid gap-4 lg:grid-cols-2 lg:items-start">
          <Card>
            <CardHeader
              title="สิ่งที่โมเดลตอบกลับมา"
              caption="ข้อความล้วน ๆ ไม่มีคำตัดสิน ไม่มีตำแหน่ง"
            />
            <CardBody className="space-y-4 px-4 py-4">
              <div>
                <div className="flex items-center gap-2">
                  <Badge tone="cited">อ้างอิงได้</Badge>
                  <span className="text-micro text-ink-faint">ค้นแล้วเจอในเอกสาร</span>
                </div>
                <p className="evidence-quote mt-2 text-ink-muted">
                  &ldquo;{SAMPLE_QUOTE}&rdquo;
                </p>
              </div>

              <div className="border-t border-line pt-4">
                <div className="flex items-center gap-2">
                  <Badge tone="dropped">ตัดทิ้ง</Badge>
                  <span className="text-micro text-ink-faint">ค้นทั้งเอกสารแล้วไม่มี</span>
                </div>
                {/* Motion 2, the same class `DroppedClaims` uses on the real screens. */}
                <p className="evidence-quote claim-struck mt-2 text-ink-muted">
                  &ldquo;{SAMPLE_FABRICATION}&rdquo;
                </p>
                <p className="mt-2 text-xs leading-relaxed text-ink-muted">
                  ข้อนี้ไม่ถูกส่งต่อให้ใครอ่าน และไม่ถูกเอาไปคิดเป็นข้อดีของผู้สมัคร
                  สิ่งที่มันเหลือไว้คือหนึ่งขีดในตัวนับของระบบ
                </p>
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="เอกสารตัวอย่าง" caption="ข้อความที่เอาไปค้นจริง" />
            <CardBody padded={false} className="px-4 py-3">
              <p className="whitespace-pre-wrap break-words font-mono text-xs leading-7 text-ink-muted">
                <SampleDocument />
              </p>
            </CardBody>
          </Card>
        </div>
      </section>

      <section className="mt-14">
        <h2 data-reveal className="text-xl font-semibold tracking-tight text-ink">
          สิ่งที่เราตั้งใจไม่ทำ
        </h2>
        <ul className="mt-6 grid gap-3 sm:grid-cols-2">
          {REFUSALS.map((item) => (
            <li key={item.title} data-reveal>
              <Card className="h-full">
                <CardBody className="px-4 py-4">
                  <h3 className="text-sm font-semibold text-ink">{item.title}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-ink-muted">{item.body}</p>
                </CardBody>
              </Card>
            </li>
          ))}
        </ul>
      </section>

      <section data-reveal className="mt-14 border-t border-line pt-8">
        <h2 className="text-xl font-semibold tracking-tight text-ink">แล้วคุณได้อะไร</h2>
        <p className="mt-2 max-w-prose text-sm leading-relaxed text-ink-muted">
          ถ้าคุณสมัครกับเรา พอคัดเสร็จคุณเปิดดูผลชุดเดียวกับที่ทีมเราอ่านได้เลย
          ทีละข้อว่าข้อไหนอ้างอิงได้ อ้างจากบรรทัดไหน ตัวอักษรตำแหน่งที่เท่าไหร่
          และข้อไหนที่เราหาหลักฐานในเอกสารของคุณไม่เจอ
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link href="/careers" className="btn btn-primary btn-lg">
            ดูตำแหน่งที่เปิดรับ
          </Link>
          <Link href="/demo" className="btn btn-secondary btn-lg">
            ลองระบบกับเอกสารตัวอย่าง
          </Link>
        </div>
      </section>
    </div>
  );
}

/**
 * The sample document with the surviving quote painted in.
 *
 * `splitAroundQuote` returning `null` is not an error state to report — it means
 * the quote is not in the document, and the honest rendering of that is the
 * document with nothing highlighted. `lib/sample.test.ts` is what keeps it from
 * happening quietly.
 */
function SampleDocument() {
  const parts = splitAroundQuote(SAMPLE_DOCUMENT, SAMPLE_QUOTE);
  if (!parts) return <>{SAMPLE_DOCUMENT}</>;

  return (
    <>
      {parts.before}
      {/* Motion 1: the same sweep and the same `cited` wash the document pane
          paints when a citation is selected on a real screening. */}
      <mark className="cite-sweep cite-sweep-cited rounded-[2px] bg-cited-wash px-px text-ink">
        {SAMPLE_QUOTE}
      </mark>
      {parts.after}
    </>
  );
}
