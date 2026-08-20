import { spanKey, useEvidenceSelection } from "@/components/DocumentPane";
import type { EvidenceRef, MatchKind } from "@/lib/api";
import { cn } from "@/lib/cn";

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
function EvidenceBody({ reference, isActive }: { reference: EvidenceRef; isActive: boolean }) {
  return (
    <>
      <span className="evidence-quote block text-ink-muted">
        &ldquo;{reference.quote.replace(/\s+/g, " ").trim()}&rdquo;
      </span>
      {/* `.evidence-coordinates`, at last. The recipe was written when the tokens
          were, and nothing called it — so this line was still `text-[10px]` in the
          faintest grey the palette has, on a screen whose entire purpose is this
          line. docs/DESIGN.md §3 said it "cannot drift back"; it had never moved.

          Motion 1's other half: selecting a citation reveals its coordinates
          beneath the quote rather than having them simply be there. */}
      <span className={cn("evidence-coordinates mt-0.5", isActive && "animate-fade-up")}>
        p{reference.page} · chars {reference.char_start}–{reference.char_end} ·{" "}
        {MATCH_LABEL[reference.match_kind]}
        {reference.is_ambiguous && (
          <span
            className="ml-1.5 text-ambiguous"
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
 *
 * **The rule this component is where you learn:** the left rule is `cited` because
 * a located quote is what the system is *asserting*, and the selected state is
 * `accent` because being the one you clicked is a *control* state. They used to be
 * the same green at two strengths, which made the selection nearly invisible and
 * spent a meaning colour on an interaction — docs/DESIGN.md §1.
 */
export function Evidence({ reference }: { reference: EvidenceRef }) {
  const selection = useEvidenceSelection();
  const isActive = selection?.activeKey === spanKey(reference);

  if (!selection) {
    return (
      <div className="mt-1 border-l-2 border-cited pl-2.5">
        <EvidenceBody reference={reference} isActive={false} />
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => selection.select(reference)}
      aria-current={isActive ? "true" : undefined}
      title="Show this quote in the document"
      className={cn(
        "ring-focus mt-1 block w-full cursor-pointer rounded-r-control border-l-2 border-cited py-0.5 pl-2.5 text-left transition-colors",
        isActive ? "bg-accent-wash" : "hover:bg-surface-sunken",
      )}
    >
      <EvidenceBody reference={reference} isActive={isActive} />
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
      <p className="text-micro font-medium uppercase tracking-wide text-ink-faint">{label}</p>
      <p className="text-sm font-medium">{value}</p>
      <Evidence reference={reference} />
    </div>
  );
}
