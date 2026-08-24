import Link from "next/link";

/**
 * A posting that is not public: closed, deleted, or never published.
 *
 * Its own file rather than the app's default, so the copy is Thai like the rest
 * of the public site — and so the reader gets somewhere to go. The API answers a
 * draft and a fiction with the same 404 on purpose (`api/app/api/routes/careers.py`),
 * so this page must not guess which of the two it is looking at.
 */
export default function PostingNotFound() {
  return (
    <div className="mx-auto max-w-3xl px-5 py-12">
      <h1 className="text-2xl font-semibold tracking-tight text-ink">ไม่พบตำแหน่งนี้</h1>
      <p className="mt-2 text-sm text-ink-muted">
        อาจปิดรับไปแล้ว หรือลิงก์ไม่ถูกต้อง
      </p>
      <Link href="/careers" className="btn btn-secondary mt-6 inline-flex">
        ดูตำแหน่งทั้งหมด
      </Link>
    </div>
  );
}
