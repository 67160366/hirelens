import Link from "next/link";

/**
 * The company's front door.
 *
 * **This route used to be the resume upload screen**, which is the clearest
 * statement of what this project was before the careers site: an internal tool
 * whose front page assumed you already worked here. The upload moved to
 * `/me/documents`, where it belongs — it is one of the applicant's own screens,
 * not the entrance to anything.
 *
 * HireLens is the employer here, not a vendor selling screening software. The
 * difference is not branding: it is what makes the screening receipt mean
 * something. A company that shows applicants the verdicts it read is making a
 * commitment about its own hiring; a product that offers that as a feature is
 * offering something its customers can switch off, which is the ATS this project
 * was founded to argue with (`docs/PLAN.md`, the careers-site section).
 *
 * Thai-first, per `docs/DESIGN.md` §8: the audience for this page is Thai
 * applicants, so the headline leads in Thai with a short English line beneath.
 * That governs the public pages only — the internal screens keep their English
 * copy, and `app/layout.tsx` says how both live under one `<html lang>`.
 *
 * A server component with no data in it, so it renders without the API. That is
 * not a temporary state: a landing page that cannot load while the backend is
 * restarting is a landing page that tells a visitor the company is broken.
 */
export default function Home() {
  return (
    <div className="mx-auto max-w-3xl px-5 py-16 sm:py-24">
      <p className="text-xs font-medium tracking-wide text-accent">HireLens</p>

      <h1 className="mt-3 text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
        เราคัดกรองเรซูเม่ด้วยข้อความที่คุณเขียนเอง
      </h1>
      <p className="mt-2 text-sm text-ink-muted" lang="en">
        Resume screening where every claim cites the exact text it came from.
      </p>

      <p className="mt-6 max-w-prose text-base leading-relaxed text-ink-muted">
        ทุกข้อสรุปที่ระบบของเราพูดถึงคุณ ต้องชี้กลับไปที่ข้อความในเอกสารของคุณได้ว่ามาจากตรงไหน
        ข้อไหนชี้ไม่ได้ เราทิ้งข้อนั้นและบอกให้รู้ ไม่ใช่เอามาแสดงเฉย ๆ
      </p>
      <p className="mt-3 max-w-prose text-base leading-relaxed text-ink-muted">
        และถ้าคุณสมัครงานกับเรา คุณเปิดดูผลการคัดกรองชุดเดียวกับที่ทีมเราอ่านได้
        — คำตัดสินทีละข้อ พร้อมข้อความที่มันอ้างอิง บนเอกสารของคุณเอง
      </p>

      <div className="mt-10 flex flex-wrap items-center gap-3">
        <Link href="/careers" className="btn btn-primary btn-lg">
          ดูตำแหน่งที่เปิดรับ
        </Link>
        <Link href="/how-we-screen" className="btn btn-secondary btn-lg">
          เราคัดกรองอย่างไร
        </Link>
      </div>

      {/* Stated here rather than only in a policy page, because it is the reason
          somebody should be willing to upload a CV at all. */}
      <p className="mt-10 max-w-prose text-xs leading-relaxed text-ink-faint">
        เอกสารที่คุณอัปโหลดถูกเก็บไว้เพื่อการคัดกรองตำแหน่งที่คุณสมัครเท่านั้น
        คุณขอสำเนาข้อมูลทั้งหมดที่เราเก็บไว้ หรือขอให้ลบทิ้งเมื่อไหร่ก็ได้
      </p>
    </div>
  );
}
