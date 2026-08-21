"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { api, type Application, type Posting, type Resume } from "@/lib/api";
import { errorMessage, useAuth } from "@/lib/auth";

/** What this screen read, and whose it is. One object rather than two pieces of
 *  state, so the owner cannot get out of step with the rows it was fetched for. */
interface LoadedForAccount {
  owner: string;
  resumes: Resume[];
  applications: Application[];
}

/**
 * One published posting, and the way in.
 *
 * **The requirements are on the page before anybody applies**, which is the whole
 * argument this site is making. An ATS that screens against a list it will not show
 * you is the thing `README.md` names as the founding pain point; printing the list
 * costs nothing and is the cheapest half of fixing it. The other half is the
 * receipt at `/me`.
 *
 * Weights are not here, and their absence is not an oversight — the public API does
 * not serve them (`api/app/api/routes/careers.py`). A weight is ranking's tuning,
 * and publishing it publishes instructions for gaming the screening. Which
 * requirements are **hard gates** is published, because being measured on something
 * secret is the complaint, not the fix.
 */
export default function PostingPage() {
  const postingId = String(useParams().id);
  const { session, ready, authorized } = useAuth();

  const [posting, setPosting] = useState<Posting | null>(null);
  const [loaded, setLoaded] = useState<LoadedForAccount | null>(null);
  const [chosen, setChosen] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .getPosting(postingId)
      .then(setPosting)
      .catch(() => setNotFound(true));
  }, [postingId]);

  // Only asked once there is a session. A stranger reading the advertisement must
  // not be met with a 401 in the console for a call they never asked for.
  //
  // **The signed-out branch clears nothing**, and that is the rule `useAuth`'s
  // rewrite bought: state that follows a session is derived from it, never reset by
  // an effect reacting to it. Clearing here would also be a frame late — the reader
  // would see the previous account's documents until React got round to the effect.
  const owner = session?.id ?? null;
  useEffect(() => {
    if (!owner) return;
    void authorized(async () => {
      setLoaded({
        owner,
        resumes: await api.listResumes(),
        applications: await api.listMyApplications(),
      });
    }).catch((caught) => setError(errorMessage(caught, "ไม่สามารถโหลดข้อมูลของคุณได้")));
  }, [owner, authorized]);

  // Nothing belonging to a previous session is ever on screen: the id it was
  // fetched under has to match the one signed in now.
  const my = loaded && loaded.owner === owner ? loaded : null;
  const already = my?.applications.find((item) => item.job_id === postingId) ?? null;
  // Every resume this account owns, whatever its status. Applying deliberately
  // does not require an extracted one — the screening happens afterwards, and
  // filtering here would turn a slow parse into a closed door.
  const mine = my?.resumes ?? [];

  async function apply() {
    if (!chosen) return;
    setError(null);
    setBusy(true);
    try {
      await authorized(async () => {
        const created = await api.applyToJob(postingId, chosen);
        setLoaded((current) =>
          current === null
            ? current
            : { ...current, applications: [...current.applications, created] },
        );
      });
    } catch (caught) {
      setError(errorMessage(caught, "ส่งใบสมัครไม่สำเร็จ"));
    } finally {
      setBusy(false);
    }
  }

  if (notFound) {
    return (
      <div className="mx-auto max-w-3xl px-5 py-12">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">ไม่พบตำแหน่งนี้</h1>
        <p className="mt-2 text-sm text-ink-muted">
          ตำแหน่งนี้อาจถูกปิดรับไปแล้ว หรือลิงก์ไม่ถูกต้อง
        </p>
        <Link href="/careers" className="btn btn-secondary mt-6 inline-flex">
          ดูตำแหน่งทั้งหมด
        </Link>
      </div>
    );
  }

  if (!posting) {
    return <p className="mx-auto max-w-3xl px-5 py-12 text-sm text-ink-muted">กำลังโหลด…</p>;
  }

  return (
    <div className="mx-auto max-w-3xl space-y-5 px-5 py-12">
      <header>
        <Link href="/careers" className="ring-focus text-micro text-ink-faint hover:text-ink">
          ← ตำแหน่งทั้งหมด
        </Link>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight text-ink">{posting.title}</h1>
        <p className="mt-1 text-xs text-ink-faint">
          {posting.location ?? "ไม่ได้ระบุสถานที่"}
        </p>
      </header>

      {posting.description && (
        <Card>
          <CardBody>
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-muted">
              {posting.description}
            </p>
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader
          title="คุณจะถูกวัดด้วยอะไร"
          caption="ทุกข้อจะถูกตัดสินแยกกัน และคำตัดสินแต่ละข้อต้องอ้างข้อความในเอกสารของคุณได้"
        />
        <CardBody padded={false}>
          <ul className="divide-y divide-line">
            {posting.requirements.map((requirement, index) => (
              <li
                key={`${requirement.label}-${index}`}
                className="flex items-start justify-between gap-3 px-4 py-3"
              >
                <div className="min-w-0">
                  <p className="text-sm text-ink">{requirement.label}</p>
                  {requirement.detail && (
                    <p className="mt-0.5 text-micro text-ink-faint">{requirement.detail}</p>
                  )}
                </div>
                {requirement.must_have && (
                  // `neutral`, not `ambiguous`. This is the employer saying what it
                  // asks for, which is not the system saying anything about a
                  // document — and `docs/DESIGN.md` §1 reserves the three meaning
                  // colours for exactly that.
                  <Badge
                    tone="neutral"
                    title="ข้อจำเป็น — ถ้าเอกสารของคุณไม่มีหลักฐานข้อนี้ คุณจะอยู่ท้ายลำดับ"
                  >
                    ข้อจำเป็น
                  </Badge>
                )}
              </li>
            ))}
            {posting.requirements.length === 0 && (
              <li className="px-4 py-3 text-sm text-ink-muted">
                ตำแหน่งนี้ยังไม่ได้ระบุข้อกำหนดไว้
              </li>
            )}
          </ul>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="สมัครตำแหน่งนี้" />
        <CardBody className="space-y-3">
          {error && <Banner tone="danger">{error}</Banner>}

          {!ready && <p className="text-sm text-ink-muted">กำลังตรวจสอบสถานะ…</p>}

          {ready && !session && (
            <p className="text-sm text-ink-muted">
              เข้าสู่ระบบหรือสร้างบัญชีก่อน แล้วกลับมาที่หน้านี้เพื่อสมัคร{" "}
              <Link href="/me" className="ring-focus rounded-control text-accent underline">
                เข้าสู่ระบบ
              </Link>
            </p>
          )}

          {ready && session && already && (
            <p className="text-sm text-ink-muted">
              คุณสมัครตำแหน่งนี้แล้ว{" "}
              <Link href="/me" className="ring-focus rounded-control text-accent underline">
                ดูใบสมัครของคุณ
              </Link>
            </p>
          )}

          {ready && session && !already && mine.length === 0 && (
            <p className="text-sm text-ink-muted">
              คุณยังไม่มีเอกสารในระบบ{" "}
              <Link
                href="/me/documents"
                className="ring-focus rounded-control text-accent underline"
              >
                อัปโหลดเรซูเม่
              </Link>{" "}
              แล้วกลับมาสมัคร
            </p>
          )}

          {ready && session && !already && mine.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <label className="sr-only" htmlFor="resume">
                เลือกเอกสารที่จะใช้สมัคร
              </label>
              <select
                id="resume"
                value={chosen}
                onChange={(event) => setChosen(event.target.value)}
                className="field w-auto min-w-[16rem]"
              >
                <option value="">เลือกเอกสาร…</option>
                {mine.map((resume) => (
                  <option key={resume.id} value={resume.id}>
                    {resume.filename}
                  </option>
                ))}
              </select>
              <Button variant="primary" onClick={() => void apply()} disabled={!chosen || busy}>
                {busy ? "กำลังส่ง…" : "ส่งใบสมัคร"}
              </Button>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
