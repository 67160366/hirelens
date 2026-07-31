import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "HireLens — explainable resume screening",
  description:
    "Every claim the system makes cites the exact text it came from. Claims it cannot cite are dropped and reported.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-stone-50 text-stone-900 antialiased dark:bg-stone-950 dark:text-stone-100">
        {children}
      </body>
    </html>
  );
}
