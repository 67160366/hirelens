import { spanKey, useEvidenceSelection } from "@/components/DocumentPane";
import type { EvidenceRef, MatchKind } from "@/lib/api";

/**
 * How a quote was matched against the source. Surfaced rather than hidden: a
 * "spacing differs" match means PDF extraction mangled the text, which is worth
 * seeing while reviewing.
 */
const MATCH_LABEL: Record<MatchKind, string> = {
  exact: "exact",
  whitespace_collapsed: "spacing differs",
  whitespace_stripped: "spacing removed",
};

/** The quote and its coordinates. Phrasing content only, so it is legal inside a button. */
function EvidenceBody({ reference }: { reference: EvidenceRef }) {
  return (
    <>
      <span className="evidence-quote block text-stone-600 dark:text-stone-400">
        &ldquo;{reference.quote.replace(/\s+/g, " ").trim()}&rdquo;
      </span>
      <span className="mt-0.5 block font-mono text-[10px] tracking-tight text-stone-400 dark:text-stone-500">
        p{reference.page} · chars {reference.char_start}–{reference.char_end} ·{" "}
        {MATCH_LABEL[reference.match_kind]}
        {reference.is_ambiguous && (
          <span
            className="ml-1.5 text-amber-600 dark:text-amber-500"
            title="This text appears more than once in the document, so the citation is not unique."
          >
            · ambiguous
          </span>
        )}
      </span>
    </>
  );
}

/**
 * A citation: the verbatim source text plus where it sits in the document.
 *
 * This component is the product's core claim rendered as UI — nothing the system
 * asserts is shown without one of these next to it. Because every claim type
 * renders through here, making it the click target locates any field in the
 * document pane without the panels above needing to know anything about it.
 *
 * With no selection context there is no document to locate anything in, so it
 * stays static rather than offering a click that would go nowhere.
 */
export function Evidence({ reference }: { reference: EvidenceRef }) {
  const selection = useEvidenceSelection();
  const isActive = selection?.activeKey === spanKey(reference);

  const border = isActive
    ? "border-emerald-500 dark:border-emerald-400"
    : "border-emerald-400/70 dark:border-emerald-500/60";

  if (!selection) {
    return (
      <div className={`mt-1 border-l-2 pl-2.5 ${border}`}>
        <EvidenceBody reference={reference} />
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => selection.select(reference)}
      aria-current={isActive ? "true" : undefined}
      title="Show this quote in the document"
      className={`mt-1 block w-full cursor-pointer border-l-2 pl-2.5 text-left transition-colors hover:bg-stone-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60 dark:hover:bg-stone-800/60 ${border}`}
    >
      <EvidenceBody reference={reference} />
    </button>
  );
}

/** A labelled value with its citation underneath. */
export function ClaimRow({
  label,
  value,
  reference,
}: {
  label: string;
  value: string;
  reference: EvidenceRef;
}) {
  return (
    <div className="py-2">
      <p className="text-[11px] font-medium uppercase tracking-wide text-stone-400 dark:text-stone-500">
        {label}
      </p>
      <p className="text-sm font-medium">{value}</p>
      <Evidence reference={reference} />
    </div>
  );
}
