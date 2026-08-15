// `eslint-config-next` v16 ships flat config directly — each subpath exports a
// `Linter.Config[]` — so the `FlatCompat` shim that used to translate the legacy
// shareable configs is gone, and `@eslint/eslintrc` with it.
//
// This is not a tidy-up. ESLint 10 drops legacy config support, and running the old
// `compat.extends("next/core-web-vitals", "next/typescript")` under it does not warn
// or degrade — it throws `Converting circular structure to JSON` from inside
// eslintrc's config validator, which reads as a bug in this repo rather than a
// removed API. Importing the flat arrays is the supported form.
import coreWebVitals from "eslint-config-next/core-web-vitals";
import typescript from "eslint-config-next/typescript";

const config = [
  ...coreWebVitals,
  ...typescript,
  {
    // `public/` holds one generated file — pdf.js's worker, copied out of
    // node_modules before every build. Linting somebody else's minified build
    // output produced six errors and 1,570 warnings about code this repo does not
    // own and cannot change.
    ignores: [".next/**", "node_modules/**", "next-env.d.ts", "public/**"],
  },
];

export default config;
