import type { DroppedClaim } from "@/lib/api";
import { droppedVocabulary, type Language } from "@/lib/evidenceCopy";

/**
 * What the model claimed and the system refused to repeat.
 *
 * Shared by the profile view and the screening view, because the server puts both
 * kinds of fabrication in the same list: a quote that is not in the document and a
 * quote aimed at a requirement that does not exist are the same class of claim, and
 * both are counted in the same hallucination rate.
 *
 * Renders nothing when nothing was dropped — an empty panel would read as a finding.
 *
 * **This panel is `dropped`, and it used to be amber.** `dropped` is the colour
 * docs/DESIGN.md §1 reserves for "a claim that could not be located, and was
 * refused" — which is exactly this — while amber is `ambiguous`, "a quote that
 * matched in more than one place". Both states appear on the same screen, so
 * painting them the same colour collapsed the product's two distinct answers into
 * one. The panel is not an error report: it is the guardrail's receipt, and the
 * copy beneath the heading is what says so.
 */
export function DroppedClaims({
  dropped,
  language = "en",
}: {
  dropped: DroppedClaim[];
  /** The product screens are English and the public site is Thai — one panel,
   *  two vocabularies, because the guardrail's receipt has to be readable by
   *  whoever is looking at it (`docs/DESIGN.md` §8). */
  language?: Language;
}) {
  const words = droppedVocabulary(language);
  if (dropped.length === 0) return null;

  return (
    <section className="rounded-card border border-dropped/40 bg-dropped-wash p-4">
      <h3 className="text-section font-semibold text-dropped">
        {words.title(dropped.length)}
      </h3>
      <p className="mt-1 text-xs text-ink-muted">{words.explanation}</p>
      <ul className="mt-3 space-y-2.5">
        {dropped.map((claim, index) => (
          <li key={`${claim.field}-${index}`} className="text-sm">
            <span className="font-mono text-micro text-dropped">{claim.field}</span>{" "}
            <span className="font-medium">{claim.value || words.noValue}</span>
            <span className="ml-1.5 text-xs text-ink-muted">
              — {words.reason(claim.reason)}
            </span>
            {claim.quote && (
              <p className="mt-0.5 text-ink-muted">
                {/* Motion 2. The strike is a painted rule rather than
                    `text-decoration`, because a decoration cannot be animated and
                    watching the refusal happen is the argument. The line is there
                    at rest, so nothing depends on the animation running. */}
                <span className="evidence-quote claim-struck">
                  {words.claimed}: &ldquo;{claim.quote}&rdquo;
                </span>
              </p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
