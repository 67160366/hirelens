"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";

import { HeroScene } from "@/components/HeroScene";

/** Does this reader want motion? Asked once per interaction rather than assumed,
 *  because `prefers-reduced-motion` neutralises CSS animation on its own but says
 *  nothing about a transform this file writes from a pointer event. */
function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * The company's front door.
 *
 * **`/` used to be the resume upload screen** — the clearest statement of what this
 * project was before the careers site: an internal tool whose front page assumed
 * you already worked here. Everything that belongs to the people who work here now
 * lives behind `/hire`, `/me` and `/usage`, and this surface shows two things and
 * nothing else: who the company is, and how to apply.
 *
 * ### The design rule that moved, and the two halves that did not
 *
 * `docs/DESIGN.md` §6 refuses gradient heroes, glow and decorative parallax. The
 * owner relaxed that on 2026-08-22 **for the marketing surface**, and §6 now says
 * so. It still governs every screen that sits beside a claim about a person.
 *
 * Two halves did not relax, and they are enforced here rather than promised:
 *
 * - **No reserved colour is spent.** Nothing on this page touches `cited`,
 *   `ambiguous` or `dropped`. The palette is `accent` and the neutrals — which is
 *   also why the aurora is indigo rather than the green a "verified" landing page
 *   would reach for.
 * - **The motion shows the mechanism.** The hero's highlight sweep is Motion 1,
 *   the one the product runs when a citation is located. The page is not
 *   decorating around the idea; it is running it.
 *
 * And §6's last bullet stands in full: nothing here claims a number the system
 * cannot back up. There is no hallucination rate, no customer count, no logo wall.
 *
 * ### Why the pointer work is in an effect rather than in React state
 *
 * A `mousemove` handler calling `setState` re-renders this whole tree ~60 times a
 * second for two numbers that only ever reach a CSS custom property. The handler
 * writes the properties directly on the stage element, so React renders once and
 * the browser composites the rest — and every layer that reads them multiplies
 * into a `translate3d`, so nothing reaches layout.
 */
export default function Home() {
  const stage = useRef<HTMLDivElement>(null);

  // Pointer parallax. Bailing out under reduced motion is not decoration: the CSS
  // block at the bottom of `globals.css` cannot neutralise a transform driven from
  // an event, so this is the only place that preference can be honoured.
  useEffect(() => {
    const element = stage.current;
    if (!element || prefersReducedMotion()) return;

    function onMove(event: PointerEvent) {
      const box = element!.getBoundingClientRect();
      element!.style.setProperty("--mx", String((event.clientX - box.left) / box.width));
      element!.style.setProperty("--my", String((event.clientY - box.top) / box.height));
    }
    // Back to rest when the pointer leaves, so the page does not hold a lean
    // nobody is causing any more.
    function onLeave() {
      element!.style.setProperty("--mx", "0.5");
      element!.style.setProperty("--my", "0.5");
    }

    element.addEventListener("pointermove", onMove);
    element.addEventListener("pointerleave", onLeave);
    return () => {
      element.removeEventListener("pointermove", onMove);
      element.removeEventListener("pointerleave", onLeave);
    };
  }, []);

  // Scroll reveal. The elements are readable until this runs and arms them, so a
  // reader with JS disabled — or one whose observer never fires — gets the page
  // rather than a blank column. Reduced motion skips the arming entirely.
  useEffect(() => {
    if (prefersReducedMotion()) return;
    const targets = Array.from(document.querySelectorAll<HTMLElement>("[data-reveal]"));
    for (const target of targets) target.classList.add("reveal-armed");

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          entry.target.classList.remove("reveal-armed");
          entry.target.classList.add("reveal-in");
          observer.unobserve(entry.target);
        }
      },
      { rootMargin: "0px 0px -12% 0px" },
    );
    for (const target of targets) observer.observe(target);
    return () => observer.disconnect();
  }, []);

  /** The spotlight that follows the cursor inside a card. Same reasoning as the
   *  stage: two numbers, straight onto the element, no re-render. */
  function spotlight(event: React.PointerEvent<HTMLElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    event.currentTarget.style.setProperty("--px", `${event.clientX - box.left}px`);
    event.currentTarget.style.setProperty("--py", `${event.clientY - box.top}px`);
  }

  return (
    <>
      <section ref={stage} className="hero-stage border-b border-line">
        {/* Layer 1 — the aurora. Indigo and violet only; the green a "verified"
            landing page would reach for is `cited`, and it is not spendable here. */}
        <div className="hero-layer hero-depth-1" aria-hidden="true">
          <span
            className="hero-blob left-[8%] top-[-14%] h-[38rem] w-[38rem] bg-[var(--accent)]"
            style={{ animationDelay: "0s" }}
          />
          <span
            className="hero-blob right-[-6%] top-[6%] h-[30rem] w-[30rem] bg-[color-mix(in_oklab,var(--accent)_60%,#a855f7)]"
            style={{ animationDelay: "-9s" }}
          />
          <span
            className="hero-blob bottom-[-24%] left-[38%] h-[26rem] w-[26rem] bg-[color-mix(in_oklab,var(--accent)_40%,#0ea5e9)]"
            style={{ animationDelay: "-17s" }}
          />
        </div>

        {/* Layer 2 — the grid, moving a little further than the aurora. */}
        <div className="hero-layer hero-grid hero-depth-2" aria-hidden="true" />

        <div className="mx-auto grid max-w-6xl items-center gap-10 px-5 py-20 sm:py-28 lg:grid-cols-[1.05fr_0.95fr]">
          <div>
            <span className="inline-flex items-center gap-2 rounded-full border border-accent/40 bg-accent-wash px-3 py-1 text-micro font-medium text-accent">
              <span className="h-1.5 w-1.5 rounded-full bg-accent" />
              HireLens · เปิดรับสมัครงาน
            </span>

            <h1 className="mt-5 text-4xl font-semibold leading-tight tracking-tight text-ink sm:text-5xl">
              เราคัดกรองเรซูเม่
              <br />
              <span className="text-accent">ด้วยข้อความที่คุณเขียนเอง</span>
            </h1>

            <p className="mt-3 text-sm text-ink-faint" lang="en">
              Resume screening where every claim cites the exact text it came from.
            </p>

            <p className="mt-6 max-w-prose text-base leading-relaxed text-ink-muted">
              ทุกข้อสรุปที่ระบบของเราพูดถึงคุณ ต้องชี้กลับไปได้ว่ามาจากข้อความไหนในเอกสารของคุณ
              ข้อไหนชี้ไม่ได้ เราทิ้งข้อนั้นและบอกให้รู้ ไม่ใช่เอามาแสดงเฉย ๆ
            </p>

            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link href="/careers" className="btn btn-primary btn-lg">
                ดูตำแหน่งที่เปิดรับ
              </Link>
              <Link href="/how-we-screen" className="btn btn-secondary btn-lg">
                เราคัดกรองอย่างไร
              </Link>
            </div>
          </div>

          {/* Layer 3 — the picture, leaning the other way from the background so the
              two separate. */}
          <div className="hero-depth-3 flex justify-center lg:justify-end">
            <HeroScene />
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-5 py-16">
        <h2 data-reveal className="text-xl font-semibold tracking-tight text-ink">
          สิ่งที่เกิดขึ้นกับเอกสารของคุณ
        </h2>
        <p data-reveal className="mt-1.5 max-w-prose text-sm text-ink-muted">
          สามขั้น และขั้นที่สามคือขั้นที่ระบบคัดกรองส่วนใหญ่ไม่มี
        </p>

        <ul className="mt-8 grid gap-4 sm:grid-cols-3">
          {STEPS.map((step, index) => (
            <li
              key={step.title}
              data-reveal
              style={{ animationDelay: `${index * 90}ms` }}
              onPointerMove={spotlight}
              className="hero-card card p-5"
            >
              <span className="font-mono text-micro tabular-nums text-accent">
                0{index + 1}
              </span>
              <h3 className="mt-2 text-sm font-semibold text-ink">{step.title}</h3>
              <p className="mt-1.5 text-xs leading-relaxed text-ink-muted">{step.body}</p>
            </li>
          ))}
        </ul>
      </section>

      <section className="border-t border-line bg-surface-sunken">
        <div className="mx-auto max-w-6xl px-5 py-14">
          <div
            data-reveal
            onPointerMove={spotlight}
            className="hero-card card flex flex-wrap items-center justify-between gap-4 p-6"
          >
            <div>
              <h2 className="text-lg font-semibold tracking-tight text-ink">
                อยากร่วมทีมกับเรา?
              </h2>
              <p className="mt-1 text-sm text-ink-muted">
                ทุกตำแหน่งบอกล่วงหน้าว่าคุณจะถูกวัดด้วยอะไร และคุณเปิดดูผลได้หลังคัดกรอง
              </p>
            </div>
            <Link href="/careers" className="btn btn-primary btn-lg shrink-0">
              ดูตำแหน่งที่เปิดรับ
            </Link>
          </div>

          <p className="mt-8 max-w-prose text-xs leading-relaxed text-ink-faint">
            เอกสารที่คุณอัปโหลดถูกเก็บไว้เพื่อการคัดกรองตำแหน่งที่คุณสมัครเท่านั้น
            คุณขอสำเนาข้อมูลทั้งหมดที่เราเก็บไว้ หรือขอให้ลบทิ้งเมื่อไหร่ก็ได้
          </p>
        </div>
      </section>
    </>
  );
}

/** Three steps, and the third is the argument. Kept beside the component rather
 *  than in a data file: it is copy, and copy that lives away from its markup is
 *  copy that stops matching it. */
const STEPS = [
  {
    title: "อ่านเอกสารของคุณ",
    body: "ระบบอ่านไฟล์ของคุณและจำไว้ว่าตัวอักษรแต่ละตัวอยู่ตำแหน่งไหน สแกนเป็นรูปก็อ่านได้ และถ้าอ่านได้ไม่ชัดพอ ระบบปฏิเสธแทนที่จะเดา",
  },
  {
    title: "ถามหาข้อความ ไม่ใช่คำตัดสิน",
    body: "โมเดลถูกถามแค่ว่า “ข้อความไหนในเอกสารนี้แสดงว่าตรงตามข้อกำหนด” ไม่เคยถูกถามว่าให้ตัดสินหรือให้คะแนน",
  },
  {
    title: "ข้อที่ชี้ไม่ได้ ถูกทิ้ง",
    body: "ทุกข้อความที่โมเดลตอบมา ระบบไปหาในเอกสารจริงเอง หาไม่เจอคือแต่งขึ้น — ถูกทิ้งและถูกนับ ไม่ได้ถูกนำมาแสดง",
  },
] as const;
