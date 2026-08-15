import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

/**
 * Vitest needed no config until `lib/auth.ts` got a test.
 *
 * Every module under `lib/` imports from `@/lib/api`, and until now every one of those
 * imports was `import type` — erased before it reaches the bundler, so nothing ever
 * had to resolve the alias. `auth.ts` imports `ApiError` and `api` as *values*, so it
 * does, and the suite failed with "Cannot find package '@/lib/api'".
 *
 * That is worth knowing rather than working around: switching `auth.ts` to a relative
 * import would have made the error go away and left the next value-import through `@/`
 * to hit the same wall. The alias mirrors `tsconfig.json`'s `paths`, so the two agree.
 *
 * No `environment` is set on purpose. `web/` runs vitest with **no DOM** — the logic
 * lives in `lib/` where it can be tested without one, and the browser is the check for
 * anything that genuinely needs a document. `lib/auth.test.ts` stubs the two globals it
 * needs rather than pulling in jsdom.
 */
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL(".", import.meta.url)),
    },
  },
});
