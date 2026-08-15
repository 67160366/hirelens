"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { EvidenceRef, GeometryReport } from "@/lib/api";
import {
  boxesForPage,
  coverageNote,
  describeGap,
  distinctSpans,
  gapForPage,
  pageOf,
  type OverlayGap,
} from "@/lib/overlay";

import { spanKey, useEvidenceSelection } from "./DocumentPane";

/**
 * The original PDF, with every citation boxed where it actually sits (M5 slice 4).
 *
 * `DocumentPane` highlights the *extracted text*, which is the coordinate space every
 * offset indexes into. This draws the same citations on the page they were read from,
 * using the character boxes `pipeline/geometry.py` measured at parse time. Both panes
 * read the same `EvidenceRef` list and the same selection, so clicking a citation in
 * either place moves both.
 *
 * All the arithmetic lives in `lib/overlay.ts`, where vitest can reach it without a
 * DOM — the lesson slices 1 and 2 each paid for. What is left here is the pdf.js
 * lifecycle and the rendering.
 */

interface Rendered {
  pageNumber: number;
  /** Canvas pixels: user-space units times `scale`. */
  height: number;
  scale: number;
  gap: OverlayGap | null;
}

type PdfTask = Awaited<ReturnType<typeof loadDocument>>;
type PdfDocument = PdfTask["doc"];

/** Loaded on demand, so pdf.js stays out of the bundle a visit never opens. */
async function loadDocument(data: ArrayBuffer) {
  const pdfjs = await import("pdfjs-dist");
  // A plain same-origin asset, copied into `public/` by `scripts/copy-pdf-worker.mjs`
  // before every dev run and every build. Not a CDN — that would put a third party in
  // the request path of a document full of somebody's personal data — and not a
  // bundler-resolved `new URL(...)`, which a green build cannot prove works.
  pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";
  // The loading task is what owns the worker, and it is what tears it down — the
  // document proxy has no `destroy` of its own. Kept together so the cleanup below
  // cannot forget which one to call.
  const task = pdfjs.getDocument({ data });
  return { task, doc: await task.promise };
}

export function PdfOverlay({
  file,
  geometry,
  references: cited,
}: {
  file: ArrayBuffer;
  geometry: GeometryReport;
  references: EvidenceRef[];
}) {
  const selection = useEvidenceSelection();
  const activeKey = selection?.activeKey ?? null;

  // Two claims resting on the same quote must not paint the same box twice — see
  // `distinctSpans`. Memoized because it feeds the effect that scrolls to the active
  // citation, and a fresh array every render would re-run it on every keystroke.
  const references = useMemo(() => distinctSpans(cited), [cited]);

  const containerRef = useRef<HTMLDivElement>(null);
  const canvases = useRef(new Map<number, HTMLCanvasElement>());
  const figures = useRef(new Map<number, HTMLElement>());

  const [document, setDocument] = useState<PdfDocument | null>(null);
  const [pages, setPages] = useState<Rendered[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Pass one: open the document and work out each page's size and whether its
  // geometry may be trusted. Nothing is painted here — the canvases do not exist
  // until this state renders them.
  useEffect(() => {
    let cancelled = false;
    let opened: PdfTask | null = null;

    const measure = async () => {
      try {
        // pdf.js takes ownership of the buffer it is handed and detaches it, so a
        // second render — a tab switch, a re-selected candidate — would be given a
        // zero-length view. Copy rather than re-fetch.
        opened = await loadDocument(file.slice(0));
        if (cancelled) return;

        const width = containerRef.current?.clientWidth ?? 0;
        const measured: Rendered[] = [];

        for (let number = 1; number <= opened.doc.numPages; number += 1) {
          const page = await opened.doc.getPage(number);
          if (cancelled) return;

          const unscaled = page.getViewport({ scale: 1 });
          // Fit the pane rather than the page's own size: a resume is read at the
          // width it is given, and every box scales with it.
          const scale = width > 0 ? width / unscaled.width : 1;

          measured.push({
            pageNumber: number,
            height: unscaled.height * scale,
            scale,
            gap: gapForPage(geometry, number, {
              width: unscaled.width,
              height: unscaled.height,
              rotation: page.rotate,
            }),
          });
        }

        if (cancelled) return;
        setDocument(opened.doc);
        setPages(measured);
      } catch (cause) {
        if (!cancelled) setError(describeFailure(cause));
      }
    };

    void measure();
    return () => {
      cancelled = true;
      void opened?.task.destroy();
    };
    // Only the bytes decide whether the document must be reopened; `geometry` and
    // `references` arrive as fresh objects on every fetch and describe the same
    // document. The gap per page is re-derived below when geometry really changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file]);

  // Pass two: paint into the canvases pass one caused to be mounted.
  useEffect(() => {
    if (!document || pages.length === 0) return;
    let cancelled = false;

    const paint = async () => {
      for (const rendered of pages) {
        const canvas = canvases.current.get(rendered.pageNumber);
        if (!canvas || cancelled) continue;

        const page = await document.getPage(rendered.pageNumber);
        if (cancelled) return;

        const viewport = page.getViewport({ scale: rendered.scale });
        canvas.width = Math.floor(viewport.width);
        canvas.height = Math.floor(viewport.height);
        await page.render({ canvas, viewport }).promise;
      }
    };

    paint().catch((cause: unknown) => {
      if (!cancelled) setError(describeFailure(cause));
    });
    return () => {
      cancelled = true;
    };
  }, [document, pages]);

  // Bring the page holding the selected citation into view, which is what the text
  // pane does for the same click.
  useEffect(() => {
    if (!activeKey) return;
    const page = pageHolding(geometry, references, activeKey);
    if (page !== null) {
      figures.current.get(page)?.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [activeKey, geometry, references]);

  // A document nothing was measured for would otherwise repeat the same sentence
  // under every page. Said once, at the top, and the captions stay quiet.
  const documentGap: OverlayGap | null = geometry.measured ? null : { kind: "not_measured" };

  return (
    <section className="rounded-lg border border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900">
      <header className="flex items-baseline justify-between gap-3 border-b border-stone-200 px-4 py-2.5 dark:border-stone-800">
        <h3 className="text-sm font-semibold">Original document</h3>
        <p className="text-[11px] text-stone-400 dark:text-stone-500">
          {pages.length > 0 ? coverageNote(geometry, pages.length) : "Rendering…"}
        </p>
      </header>

      <div ref={containerRef} className="max-h-[70vh] space-y-4 overflow-y-auto px-4 py-3">
        {error && (
          <p className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-800 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-400">
            {error}
          </p>
        )}
        {!error && pages.length === 0 && (
          <p className="text-xs text-stone-500 dark:text-stone-400">Rendering the document…</p>
        )}
        {documentGap && (
          <p className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-400">
            {describeGap(documentGap)}
          </p>
        )}

        {pages.map((rendered) => {
          const page = pageOf(geometry, rendered.pageNumber);
          const drawable = rendered.gap === null && page !== null;

          return (
            <figure
              key={rendered.pageNumber}
              ref={(element) => {
                if (element) figures.current.set(rendered.pageNumber, element);
                else figures.current.delete(rendered.pageNumber);
              }}
              className="space-y-1.5"
            >
              <div className="relative w-full" style={{ height: `${rendered.height}px` }}>
                <canvas
                  ref={(element) => {
                    if (element) canvases.current.set(rendered.pageNumber, element);
                    else canvases.current.delete(rendered.pageNumber);
                  }}
                  className="absolute inset-0 h-full w-full rounded border border-stone-200 bg-white dark:border-stone-800"
                />
                {drawable &&
                  references.flatMap((reference) =>
                    boxesForPage(page, reference).map((box, index) => {
                      const key = spanKey(reference);
                      return (
                        <button
                          key={`${key}-${index}`}
                          type="button"
                          aria-label={`Citation at characters ${reference.char_start}–${reference.char_end}`}
                          onClick={() => selection?.select(reference)}
                          className={`absolute rounded-[1px] transition-colors ${boxClass(reference.is_ambiguous, key === activeKey)}`}
                          style={{
                            // pdfplumber measures `top` from the top of the page and
                            // pdf.js paints from the top-left, so at rotation 0 the
                            // only conversion is the scale — and `gapForPage` refuses
                            // every page where that is not true.
                            left: `${box.left * rendered.scale}px`,
                            top: `${box.top * rendered.scale}px`,
                            width: `${Math.max(box.width * rendered.scale, 2)}px`,
                            height: `${box.height * rendered.scale}px`,
                          }}
                        />
                      );
                    }),
                  )}
              </div>

              <figcaption className="px-1 text-[11px] text-stone-400 dark:text-stone-500">
                Page {rendered.pageNumber}
                {rendered.gap && !documentGap && (
                  <span className="ml-2 text-amber-700 dark:text-amber-500">
                    {describeGap(rendered.gap)}
                  </span>
                )}
              </figcaption>
            </figure>
          );
        })}
      </div>
    </section>
  );
}

function describeFailure(cause: unknown): string {
  return cause instanceof Error
    ? `The document could not be displayed: ${cause.message}`
    : "The document could not be displayed.";
}

function boxClass(isAmbiguous: boolean, isActive: boolean): string {
  // The same vocabulary as the text pane: amber for a quote that matched in more than
  // one place, emerald otherwise, and a ring on the selected one.
  if (isAmbiguous) {
    return isActive
      ? "bg-amber-400/45 ring-2 ring-amber-600"
      : "bg-amber-300/25 hover:bg-amber-300/40";
  }
  return isActive
    ? "bg-emerald-400/45 ring-2 ring-emerald-600"
    : "bg-emerald-300/25 hover:bg-emerald-300/40";
}

/** Which page holds the selected citation, or null when no page can show it. */
function pageHolding(
  geometry: GeometryReport,
  references: EvidenceRef[],
  activeKey: string,
): number | null {
  for (const page of geometry.pages) {
    for (const reference of references) {
      if (spanKey(reference) !== activeKey) continue;
      if (boxesForPage(page, reference).length > 0) return page.page_number;
    }
  }
  return null;
}
