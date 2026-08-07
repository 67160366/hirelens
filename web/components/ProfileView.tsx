import { ClaimRow, Evidence } from "@/components/Evidence";
import type { DroppedClaim, ExtractedProfile, RejectReason, Resume } from "@/lib/api";

const REJECT_LABEL: Record<RejectReason, string> = {
  not_found: "no matching text in the document",
  too_short: "quote too short to identify a source",
  empty: "no quote supplied",
};

function StatsBar({ profile }: { profile: ExtractedProfile }) {
  const { stats } = profile;
  const clean = stats.dropped === 0;

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg border border-stone-200 bg-white px-4 py-3 text-sm dark:border-stone-800 dark:bg-stone-900">
      <span>
        <strong className="tabular-nums">
          {stats.verified}/{stats.total_claims}
        </strong>{" "}
        <span className="text-stone-500 dark:text-stone-400">claims verified</span>
      </span>
      <span
        className={
          clean ? "text-emerald-700 dark:text-emerald-400" : "text-amber-700 dark:text-amber-400"
        }
      >
        <strong className="tabular-nums">{(stats.hallucination_rate * 100).toFixed(1)}%</strong>{" "}
        unverifiable
      </span>
      <span className="text-stone-500 dark:text-stone-400">
        {stats.attempts} model {stats.attempts === 1 ? "call" : "calls"}
      </span>
    </div>
  );
}

function DroppedSection({ dropped }: { dropped: DroppedClaim[] }) {
  return (
    <section className="rounded-lg border border-amber-300 bg-amber-50/70 p-4 dark:border-amber-900/60 dark:bg-amber-950/30">
      <h3 className="text-sm font-semibold text-amber-900 dark:text-amber-300">
        Excluded — could not be traced to the document ({dropped.length})
      </h3>
      <p className="mt-1 text-xs text-amber-800/80 dark:text-amber-400/80">
        The model asserted these, but the text it cited is not in the file. They are shown here
        rather than silently discarded.
      </p>
      <ul className="mt-3 space-y-2.5">
        {dropped.map((claim, index) => (
          <li key={`${claim.field}-${index}`} className="text-sm">
            <span className="font-mono text-[11px] text-amber-700 dark:text-amber-500">
              {claim.field}
            </span>{" "}
            <span className="font-medium">{claim.value || "(no value)"}</span>
            <span className="ml-1.5 text-xs text-amber-700/80 dark:text-amber-500/80">
              — {REJECT_LABEL[claim.reason]}
            </span>
            {claim.quote && (
              <p className="evidence-quote mt-0.5 text-amber-800/70 line-through dark:text-amber-500/60">
                claimed: &ldquo;{claim.quote}&rdquo;
              </p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Panel({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  if (count === 0) return null;
  return (
    <section className="rounded-lg border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      <h3 className="text-sm font-semibold">
        {title} <span className="text-stone-400 dark:text-stone-500">({count})</span>
      </h3>
      <div className="mt-2 divide-y divide-stone-100 dark:divide-stone-800">{children}</div>
    </section>
  );
}

export function ProfileView({
  resume,
  profile,
}: {
  resume: Resume;
  profile: ExtractedProfile | null;
}) {
  // `dead_lettered` reads the same way to a user — nothing came out of it — and
  // differs only in that it is worth trying again, which the retry control says.
  if (resume.status === "failed" || resume.status === "dead_lettered") {
    return (
      <div className="rounded-lg border border-red-300 bg-red-50 p-4 dark:border-red-900/60 dark:bg-red-950/30">
        <h3 className="text-sm font-semibold text-red-900 dark:text-red-300">
          Could not process {resume.filename}
        </h3>
        <p className="mt-1 text-sm text-red-800 dark:text-red-400">{resume.failure_reason}</p>
      </div>
    );
  }

  if (!profile) {
    return (
      <div className="rounded-lg border border-stone-200 bg-white p-4 text-sm dark:border-stone-800 dark:bg-stone-900">
        <p className="font-medium">Parsed, but not extracted</p>
        <p className="mt-1 text-stone-500 dark:text-stone-400">
          {resume.failure_reason ?? "Extraction has not run for this resume yet."}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <StatsBar profile={profile} />

      {resume.pages_from_ocr.length > 0 && (
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 text-xs text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-300">
          {resume.pages_from_ocr.length === 1 ? "Page" : "Pages"}{" "}
          {resume.pages_from_ocr.join(", ")} had no text layer and{" "}
          {resume.pages_from_ocr.length === 1 ? "was" : "were"} read by OCR. Quotes from{" "}
          {resume.pages_from_ocr.length === 1 ? "it" : "them"} match what was recognized, which may
          differ from what was printed.
        </p>
      )}

      {resume.pages_without_text.length > 0 && (
        <p className="rounded-lg border border-sky-200 bg-sky-50 px-4 py-2.5 text-xs text-sky-900 dark:border-sky-900/60 dark:bg-sky-950/30 dark:text-sky-300">
          {resume.pages_without_text.length === 1 ? "Page" : "Pages"}{" "}
          {resume.pages_without_text.join(", ")} yielded no readable text, so nothing on{" "}
          {resume.pages_without_text.length === 1 ? "it" : "them"} could be cited.
        </p>
      )}

      <section className="rounded-lg border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
        <div className="divide-y divide-stone-100 dark:divide-stone-800">
          {profile.full_name && (
            <ClaimRow
              label="Name"
              value={profile.full_name.value}
              reference={profile.full_name.evidence}
            />
          )}
          {profile.headline && (
            <ClaimRow
              label="Headline"
              value={profile.headline.value}
              reference={profile.headline.evidence}
            />
          )}
          {profile.years_experience && (
            <ClaimRow
              label="Years of experience"
              value={profile.years_experience.value}
              reference={profile.years_experience.evidence}
            />
          )}
          <div className="py-2">
            <p className="text-[11px] font-medium uppercase tracking-wide text-stone-400 dark:text-stone-500">
              Seniority
            </p>
            <p className="text-sm font-medium">{profile.seniority}</p>
            {profile.seniority_evidence ? (
              <Evidence reference={profile.seniority_evidence} />
            ) : (
              <p className="mt-1 text-xs text-stone-400 dark:text-stone-500">
                Not stated in the document. Left as unknown rather than inferred from job titles.
              </p>
            )}
          </div>
        </div>
      </section>

      <Panel title="Skills" count={profile.skills.length}>
        {profile.skills.map((skill, index) => (
          <div key={`${skill.value}-${index}`} className="py-2">
            <p className="text-sm font-medium">{skill.value}</p>
            <Evidence reference={skill.evidence} />
          </div>
        ))}
      </Panel>

      <Panel title="Experience" count={profile.experiences.length}>
        {profile.experiences.map((role, index) => (
          <div key={`${role.company}-${index}`} className="py-2">
            <p className="text-sm font-medium">
              {role.title} <span className="text-stone-400">at</span> {role.company}
            </p>
            <p className="text-xs text-stone-500 dark:text-stone-400">
              {role.start} – {role.end}
            </p>
            <Evidence reference={role.evidence} />
          </div>
        ))}
      </Panel>

      <Panel title="Education" count={profile.education.length}>
        {profile.education.map((entry, index) => (
          <div key={`${entry.institution}-${index}`} className="py-2">
            <p className="text-sm font-medium">{entry.credential}</p>
            <p className="text-xs text-stone-500 dark:text-stone-400">{entry.institution}</p>
            <Evidence reference={entry.evidence} />
          </div>
        ))}
      </Panel>

      {profile.dropped.length > 0 && <DroppedSection dropped={profile.dropped} />}
    </div>
  );
}
