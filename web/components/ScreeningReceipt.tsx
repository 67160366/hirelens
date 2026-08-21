"use client";

import { DroppedClaims } from "@/components/DroppedClaims";
import { EvidenceSelectionProvider } from "@/components/DocumentPane";
import { DocumentViewer } from "@/components/DocumentViewer";
import { Evidence } from "@/components/Evidence";
import { Badge } from "@/components/ui/Badge";
import { Banner } from "@/components/ui/Banner";
import type { EvidenceRef, Receipt } from "@/lib/api";
import { NOT_EVIDENCED_EXPLANATION } from "@/lib/screening";

/** Every citation on the receipt, so the document pane can highlight them.
 *
 *  Only `met` requirements have any — the verdict is derived from whether a quote
 *  resolved, so `not_evidenced` carries an empty list by construction rather than
 *  by filtering. Written as a filter anyway: an assumption about a payload shape is
 *  the kind of thing that stays true until it does not. */
function citations(receipt: Receipt): EvidenceRef[] {
  return receipt.requirements
    .filter((requirement) => requirement.verdict === "met")
    .flatMap((requirement) => requirement.evidence);
}

/**
 * The screening receipt: what the employer read about you, on your own document.
 *
 * **This is the screen the project was founded for.** `README.md` names the pain
 * point as candidates rejected by automated screening with no explanation, and
 * until now every surface in this app served the side doing the rejecting — the
 * applicant could export their verdicts (`privacy_service`) but could not look at
 * them.
 *
 * Three things are deliberately absent, and each is the same decision made three
 * times:
 *
 * - **No score.** A score is comparative and means nothing about one person alone;
 *   showing it invites "why 62%", which this system cannot answer honestly. The
 *   API does not serve one.
 * - **No rank.** Where you came against other applicants is a fact about them.
 * - **No weight.** Ranking's tuning, never seen by the judge.
 *
 * What *is* here is the whole mechanism: each requirement judged on its own, the
 * exact quote that settled it, and the offsets that quote sits at — clickable, so
 * the reader watches it highlight in their own document rather than taking the
 * citation on trust. `not_evidenced` says what it means in words, because "we
 * could not find it" and "you do not have it" are different sentences and only one
 * of them is true.
 */
export function ScreeningReceipt({
  receipt,
  resumeFilename,
  resumeId,
  authorized,
}: {
  receipt: Receipt;
  resumeFilename: string;
  resumeId: string;
  authorized: <T>(call: () => Promise<T>) => Promise<T>;
}) {
  const met = receipt.requirements.filter((item) => item.verdict === "met").length;
  // The ISO date, not `toLocaleDateString()`. Found by driving it: with the browser
  // set to Thai that rendered `20/8/2569` — the Buddhist year, correct for a Thai
  // reader and baffling in the middle of an English screen, and ambiguous either way
  // once the day and month are both under 13. A receipt is a document about a person;
  // its date should read the same to everyone who is handed it.
  const screenedOn = receipt.screened_at.slice(0, 10);

  return (
    <EvidenceSelectionProvider>
      <div className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-sm font-semibold text-ink">
            What we read in your document
          </h3>
          <span className="font-mono text-micro tabular-nums text-ink-faint">
            {met}/{receipt.requirements.length} evidenced · {screenedOn}
          </span>
        </div>

        {receipt.reason && (
          // `info`, not `danger`. A rejection reason is a decision somebody made
          // about a person; the three reserved colours say what the system found in
          // a *document* (`docs/DESIGN.md` §1), and spending one here would make a
          // human judgement look like a machine verdict.
          <Banner tone="info">
            <span className="font-medium">Reason given:</span> {receipt.reason}
          </Banner>
        )}

        {receipt.posting_changed_since && (
          <p className="text-micro text-ink-faint">
            The posting has been edited since this was screened. The verdicts below are
            what was actually read, against the requirements as they stood then.
          </p>
        )}

        <ul className="divide-y divide-line rounded-card border border-line">
          {receipt.requirements.map((requirement, index) => (
            <li key={`${requirement.label}-${index}`} className="px-3 py-2.5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm text-ink">{requirement.label}</span>
                {requirement.must_have && <Badge tone="neutral">must have</Badge>}
                <span className="ml-auto">
                  {requirement.verdict === "met" ? (
                    // `cited` earns its token here: this is the system saying it
                    // located this claim in this document, which is exactly what the
                    // colour is reserved for.
                    <Badge tone="cited">Evidenced</Badge>
                  ) : (
                    <Badge tone="neutral">No citable evidence</Badge>
                  )}
                </span>
              </div>

              {requirement.verdict === "met" ? (
                requirement.evidence.map((reference, position) => (
                  <Evidence key={`${reference.char_start}-${position}`} reference={reference} />
                ))
              ) : (
                <p className="mt-1 text-micro text-ink-faint">{NOT_EVIDENCED_EXPLANATION}</p>
              )}
            </li>
          ))}
        </ul>

        {/* The guardrail, on the applicant's own document. A claim the model made
            that could not be located was refused, and the person it was about is
            entitled to see that it happened. */}
        <DroppedClaims dropped={receipt.dropped} />

        {receipt.document_text && (
          <DocumentViewer
            resumeId={resumeId}
            filename={resumeFilename}
            text={receipt.document_text}
            references={citations(receipt)}
            authorized={authorized}
          />
        )}
      </div>
    </EvidenceSelectionProvider>
  );
}
