/**
 * Put pdf.js's worker where the browser can fetch it (M5 slice 4).
 *
 * pdf.js parses and rasterizes in a web worker, and the worker file has to be
 * reachable by URL at runtime. Two ways were considered and one of them is a trap:
 *
 * - `new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url)` relies on the
 *   bundler resolving a **bare package specifier** inside `new URL`, which is a
 *   webpack/Vite behaviour rather than a guarantee. `next build` runs Turbopack since
 *   `next@16`, and a green build says nothing about whether the URL resolves in a
 *   browser — the same class of trap as the standalone regression the `next@16`
 *   change had to check by hand (vercel/next.js#88844).
 * - Copying the file into `public/` makes it a plain same-origin asset with a stable
 *   path. No bundler is involved, so there is nothing that can silently stop working.
 *
 * A CDN was never an option: it would put a third party in the request path of a
 * document full of somebody's personal data.
 *
 * Run by the `predev` and `prebuild` hooks, so it happens in the Docker builder stage
 * too, and the copy is gitignored rather than vendored — a megabyte of somebody
 * else's build output does not belong in this history.
 */

import { copyFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const root = join(dirname(fileURLToPath(import.meta.url)), "..");

const source = join(dirname(require.resolve("pdfjs-dist/package.json")), "build", "pdf.worker.min.mjs");
const target = join(root, "public", "pdf.worker.min.mjs");

mkdirSync(join(root, "public"), { recursive: true });
copyFileSync(source, target);

console.log(`pdf.js worker copied to public/${"pdf.worker.min.mjs"}`);
