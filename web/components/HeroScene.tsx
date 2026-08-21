/**
 * The picture on the landing page — a résumé being read, drawn rather than photographed.
 *
 * **A generated SVG instead of a stock photograph**, and that is a decision worth
 * a sentence. A photo of people in an office says "a company exists"; this says
 * what this company's product actually does — a line of a CV highlighted, and a
 * coordinate underneath naming the exact characters it sits at. It also costs no
 * request, no licence and no 400KB, scales to any width without a second asset,
 * and repaints correctly in both themes because every colour is a token.
 *
 * The highlight sweeps once, on a loop, because that sweep **is** Motion 1 from
 * `docs/DESIGN.md` §4 — the one the product uses when a citation is selected. The
 * hero is showing the mechanism rather than decorating around it, which is the
 * half of §6 that did not relax.
 *
 * `aria-hidden`: everything here is said in words beside it, and a screen reader
 * announcing a decorative diagram twice is worse than silence.
 */
export function HeroScene() {
  return (
    <svg
      viewBox="0 0 420 300"
      className="h-auto w-full max-w-md"
      role="presentation"
      aria-hidden="true"
    >
      <defs>
        <clipPath id="hero-page">
          <rect x="24" y="18" width="240" height="264" rx="10" />
        </clipPath>
      </defs>

      {/* The document */}
      <rect
        x="24"
        y="18"
        width="240"
        height="264"
        rx="10"
        className="fill-[var(--surface)] stroke-[var(--line-strong)]"
        strokeWidth="1.5"
      />

      <g clipPath="url(#hero-page)">
        {/* Name and headline */}
        <rect x="44" y="42" width="104" height="11" rx="3" className="fill-[var(--ink)]" opacity="0.82" />
        <rect x="44" y="60" width="150" height="6" rx="3" className="fill-[var(--ink-faint)]" opacity="0.5" />

        {/* Section rule */}
        <rect x="44" y="84" width="60" height="6" rx="3" className="fill-[var(--ink-muted)]" opacity="0.65" />

        {/* Body lines */}
        {[102, 116, 130, 158, 172, 186, 214, 228].map((y, index) => (
          <rect
            key={y}
            x="44"
            y={y}
            width={index % 3 === 2 ? 118 : 176}
            height="6"
            rx="3"
            className="fill-[var(--ink-faint)]"
            opacity="0.34"
          />
        ))}

        {/* The cited line: a highlight that sweeps in, then holds, then repeats.
            Scaling `width` would be a layout property; this scales a transform on
            its own group, which is what §4 asks for. */}
        <g transform="translate(44 140)">
          <rect
            width="176"
            height="12"
            rx="3"
            className="fill-[var(--accent)]"
            opacity="0.22"
            style={{ transformOrigin: "left center", animation: "hero-sweep 6s ease-in-out infinite" }}
          />
          <rect y="3" width="176" height="6" rx="3" className="fill-[var(--ink)]" opacity="0.62" />
        </g>
      </g>

      {/* The citation callout, pointing at that line */}
      <path
        d="M226 146 H286"
        className="stroke-[var(--accent)]"
        strokeWidth="1.5"
        strokeDasharray="3 3"
        opacity="0.8"
      />
      <circle cx="226" cy="146" r="3.5" className="fill-[var(--accent)]" />

      <g transform="translate(286 124)">
        <rect
          width="118"
          height="44"
          rx="8"
          className="fill-[var(--surface-raised)] stroke-[var(--accent)]"
          strokeWidth="1.5"
          opacity="0.98"
        />
        <text x="12" y="19" className="fill-[var(--ink)]" fontSize="9" fontFamily="var(--font-plex-mono)">
          p1 · chars
        </text>
        <text x="12" y="32" className="fill-[var(--accent)]" fontSize="9" fontFamily="var(--font-plex-mono)">
          161–214 · exact
        </text>
      </g>

      {/* A refused claim, struck through — the other half of the idea */}
      <g transform="translate(286 194)">
        <rect
          width="118"
          height="30"
          rx="8"
          className="fill-[var(--surface-raised)] stroke-[var(--line-strong)]"
          strokeWidth="1.5"
        />
        <rect x="12" y="12" width="72" height="6" rx="3" className="fill-[var(--ink-faint)]" opacity="0.55" />
        <path d="M12 15 H84" className="stroke-[var(--ink-muted)]" strokeWidth="1.5" />
      </g>
    </svg>
  );
}
