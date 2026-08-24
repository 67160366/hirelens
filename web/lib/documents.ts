import type { Resume, ResumeStatus } from "@/lib/api";

/**
 * How a document's own state is worded in the library.
 *
 * `lib/screening.ts` does this for a screening's status and says why it lives in
 * `lib/`: a label written inside a component is a label vitest cannot reach. The
 * two vocabularies are deliberately separate — a resume is never `completed` and
 * a screening is never `parsed`, and making one table wear the other's words is
 * the mistake `docs/HANDOFF.md` §5 records refusing at the database level.
 *
 * **The tone is not decoration here.** `docs/DESIGN.md` §1 reserves `cited`,
 * `ambiguous` and `dropped` for what the system says about a *document*, and a
 * parse failure is exactly that: this file could not be read. The upload screen
 * has spent `ambiguous` on a retryable failure since the redesign, with the same
 * argument in a comment; this is that argument written once and applied to every
 * row.
 */
export type DocumentTone = "cited" | "ambiguous" | "dropped" | "neutral";

interface DocumentState {
  label: string;
  tone: DocumentTone;
  /** One line under the row, in the reader's terms rather than the worker's. */
  detail: string;
}

const STATES: Record<ResumeStatus, DocumentState> = {
  pending: {
    label: "Queued",
    tone: "neutral",
    detail: "Waiting for a worker to pick it up.",
  },
  processing: {
    label: "Reading",
    tone: "neutral",
    detail: "Parsing the file and verifying every quote against it.",
  },
  parsed: {
    label: "Text only",
    tone: "neutral",
    detail: "The text came out, but nothing has been extracted from it yet.",
  },
  extracted: {
    label: "Ready",
    tone: "cited",
    detail: "Every claim in it cites the text it came from.",
  },
  failed: {
    label: "Could not be read",
    tone: "dropped",
    detail: "This document cannot be processed as it is.",
  },
  dead_lettered: {
    label: "Gave up after retrying",
    tone: "ambiguous",
    detail: "Something went wrong repeatedly. Worth trying again once the cause is fixed.",
  },
};

export function documentState(status: ResumeStatus): DocumentState {
  return STATES[status];
}

/** Every status the API can send, derived from the map so the two cannot diverge. */
export const DOCUMENT_STATUSES = Object.keys(STATES) as ResumeStatus[];

/**
 * The line under a document's name: what it is, rather than what happened to it.
 *
 * Size in whole units and page count when there is one. A `.docx` has no page
 * breaks until Word renders it, so the API sends no count for one and this says
 * nothing rather than guessing — the same refusal the upload hint already makes
 * about its citations reporting page 1.
 */
export function documentSummary(resume: Resume): string {
  const parts = [formatSize(resume.size_bytes)];
  if (resume.page_count !== null) {
    parts.push(`${resume.page_count} ${resume.page_count === 1 ? "page" : "pages"}`);
  }
  if (resume.pages_from_ocr.length > 0) {
    parts.push(
      `${resume.pages_from_ocr.length} ${
        resume.pages_from_ocr.length === 1 ? "page" : "pages"
      } read by OCR`,
    );
  }
  return parts.join(" · ");
}

/** Bytes as a person reads them. Never "0.0 MB" for a real file. */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
