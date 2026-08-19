import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, IBM_Plex_Sans_Thai_Looped } from "next/font/google";

import "./globals.css";

/**
 * One superfamily across Latin, Thai and monospace — see `docs/DESIGN.md` §2.
 *
 * Plex Sans is the Latin companion Plex Thai was drawn against, so a résumé line
 * mixing Thai and English sits on one rhythm instead of visibly switching typeface
 * mid-sentence. This repo briefly paired Plex Thai with Inter, which is two
 * different x-heights in the same line; and before that it named three families in
 * the stylesheet and served none, so on Windows everything fell through to Segoe
 * UI — a face with no Thai glyphs at all.
 */
const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  variable: "--font-plex-sans",
  display: "swap",
});

// Looped is the conventional Thai reading form for body text; the loopless cut reads
// as display. Neither Thai face has a variable weight, so the three the tree actually
// uses are enumerated.
const plexThai = IBM_Plex_Sans_Thai_Looped({
  subsets: ["thai", "latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-thai",
  display: "swap",
});

// Every quote and every character offset is set here. A citation is a claim about
// exact characters, and tabular figures are what stop two offsets that differ by one
// from looking identical.
const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "HireLens — explainable resume screening",
  description:
    "Every claim the system makes cites the exact text it came from. Claims it cannot cite are dropped and reported.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${plexSans.variable} ${plexThai.variable} ${plexMono.variable}`}
    >
      <body className="min-h-screen bg-paper font-sans text-ink antialiased">{children}</body>
    </html>
  );
}
