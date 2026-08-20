import { DroppedClaims } from "@/components/DroppedClaims";
import { ClaimRow, Evidence } from "@/components/Evidence";
import { EvidenceStatsBar } from "@/components/EvidenceStatsBar";
import { Banner } from "@/components/ui/Banner";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import type { ExtractedProfile, Resume } from "@/lib/api";

function Panel({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  if (count === 0) return null;
  return (
    <Card>
      <CardHeader title={<>{title} <span className="text-ink-faint">({count})</span></>} />
      <CardBody className="divide-y divide-line px-4">{children}</CardBody>
    </Card>
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
      <Banner tone="danger">
        <strong className="block font-semibold">Could not process {resume.filename}</strong>
        <span className="mt-1 block">{resume.failure_reason}</span>
      </Banner>
    );
  }

  if (!profile) {
    return (
      <Card className="p-4 text-sm">
        <p className="font-medium">Parsed, but not extracted</p>
        <p className="mt-1 text-ink-muted">
          {resume.failure_reason ?? "Extraction has not run for this resume yet."}
        </p>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <EvidenceStatsBar stats={profile.stats} />

      {resume.pages_from_ocr.length > 0 && (
        // `warn`, which is `ambiguous`: a recognized page is exactly the case where
        // a quote may not be the characters that were printed.
        <Banner tone="warn" className="text-xs">
          {resume.pages_from_ocr.length === 1 ? "Page" : "Pages"}{" "}
          {resume.pages_from_ocr.join(", ")} had no text layer and{" "}
          {resume.pages_from_ocr.length === 1 ? "was" : "were"} read by OCR. Quotes from{" "}
          {resume.pages_from_ocr.length === 1 ? "it" : "them"} match what was recognized, which may
          differ from what was printed.
        </Banner>
      )}

      {resume.pages_without_text.length > 0 && (
        // `info`, and neutral on purpose: a page with no text layer is a fact about
        // the document, not a fault in it. Sky was a fifth colour with no meaning
        // assigned to it, which is what the token set exists to stop.
        <Banner tone="info" className="text-xs">
          {resume.pages_without_text.length === 1 ? "Page" : "Pages"}{" "}
          {resume.pages_without_text.join(", ")} yielded no readable text, so nothing on{" "}
          {resume.pages_without_text.length === 1 ? "it" : "them"} could be cited.
        </Banner>
      )}

      <Card>
        <CardBody className="divide-y divide-line px-4">
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
            <p className="text-micro font-medium uppercase tracking-wide text-ink-faint">
              Seniority
            </p>
            <p className="text-sm font-medium">{profile.seniority}</p>
            {profile.seniority_evidence ? (
              <Evidence reference={profile.seniority_evidence} />
            ) : (
              <p className="mt-1 text-xs text-ink-muted">
                Not stated in the document. Left as unknown rather than inferred from job titles.
              </p>
            )}
          </div>
        </CardBody>
      </Card>

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
              {role.title} <span className="text-ink-faint">at</span> {role.company}
            </p>
            <p className="text-xs text-ink-muted">
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
            <p className="text-xs text-ink-muted">{entry.institution}</p>
            <Evidence reference={entry.evidence} />
          </div>
        ))}
      </Panel>

      <DroppedClaims dropped={profile.dropped} />
    </div>
  );
}
