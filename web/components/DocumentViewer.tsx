"use client";

import { useEffect, useState } from "react";

import type { EvidenceRef, GeometryReport } from "@/lib/api";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/auth";
import { canRenderOriginal } from "@/lib/overlay";

import { DocumentPane } from "./DocumentPane";
import { PdfOverlay } from "./PdfOverlay";

/**
 * The source document, as text or as the page it was printed on (M5 slice 4).
 *
 * Two views of one thing, and the split is the honest one: `DocumentPane` shows the
 * exact string every offset indexes into, and `PdfOverlay` shows where those
 * characters sit on the page. The text view is the default because it is the one that
 * always works — a `.docx` has no pages, a scanned page has no glyph boxes, and a
 * resume uploaded before migration `0010` was never measured.
 *
 * This component owns the switch and the two fetches, so `DocumentPane` — M1's, and
 * load-bearing — is untouched and still used directly wherever there is no original
 * to offer.
 */
export function DocumentViewer({
  resumeId,
  filename,
  text,
  references,
  authorized,
}: {
  resumeId: string;
  filename: string | null;
  text: string;
  references: EvidenceRef[];
  /** `useAuth().authorized`, so these reads inherit the refresh-once-on-401 path. */
  authorized: <T>(call: () => Promise<T>) => Promise<T>;
}) {
  const [showOriginal, setShowOriginal] = useState(false);
  const [file, setFile] = useState<ArrayBuffer | null>(null);
  const [geometry, setGeometry] = useState<GeometryReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const offered = canRenderOriginal(filename);

  // Fetched when the tab is first opened rather than on mount. The bytes are the
  // largest thing this screen can ask for, and most visits never open them — the
  // same reason the geometry is its own route instead of a field on the profile.
  useEffect(() => {
    if (!showOriginal || file !== null) return;
    let cancelled = false;

    void (async () => {
      try {
        const [bytes, report] = await Promise.all([
          authorized(() => api.getResumeFile(resumeId)),
          authorized(() => api.getResumeGeometry(resumeId)),
        ]);
        if (cancelled) return;
        setFile(bytes);
        setGeometry(report);
      } catch (cause) {
        if (!cancelled) setError(errorMessage(cause, "Could not fetch the original document"));
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [showOriginal, file, resumeId, authorized]);

  if (!offered) return <DocumentPane text={text} references={references} />;

  return (
    <div className="space-y-2 lg:sticky lg:top-6">
      <div className="flex items-center gap-1">
        <Tab active={!showOriginal} onClick={() => setShowOriginal(false)}>
          Extracted text
        </Tab>
        <Tab active={showOriginal} onClick={() => setShowOriginal(true)}>
          Original document
        </Tab>
      </div>

      {!showOriginal && <DocumentPane text={text} references={references} />}

      {showOriginal &&
        (error ? (
          <p className="rounded-lg border border-red-300 bg-red-50 px-4 py-2.5 text-xs text-red-800 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-400">
            {error}
          </p>
        ) : file && geometry ? (
          <PdfOverlay file={file} geometry={geometry} references={references} />
        ) : (
          <p className="rounded-lg border border-stone-200 px-4 py-3 text-xs text-stone-500 dark:border-stone-800 dark:text-stone-400">
            Fetching the original document…
          </p>
        ))}
    </div>
  );
}

function Tab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
        active
          ? "bg-stone-900 text-white dark:bg-stone-100 dark:text-stone-900"
          : "text-stone-500 hover:bg-stone-100 dark:text-stone-400 dark:hover:bg-stone-800"
      }`}
    >
      {children}
    </button>
  );
}
