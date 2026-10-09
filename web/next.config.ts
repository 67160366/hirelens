import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // Emit a self-contained server bundle with only the dependencies actually
  // reached, so the runtime image needs no node_modules at all. Without this the
  // image has to carry the full dev tree — Next 15 pulls in sharp and the whole
  // TypeScript toolchain, none of which a running server uses.
  // Vercel's adapter packages the server itself. Next 16.3's standalone
  // finalizer expects a trace file that adapter builds do not emit.
  output: process.env.VERCEL ? undefined : "standalone",
  async rewrites() {
    const upstream = process.env.API_PROXY_BASE;
    if (!upstream) return [];
    const url = new URL(upstream);
    if (url.protocol !== "https:" || url.username || url.password ||
        url.search || url.hash || url.pathname !== "/") {
      throw new Error("API_PROXY_BASE must be an HTTPS origin without credentials or a path");
    }
    return [{ source: "/api/:path*", destination: `${url.origin}/:path*` }];
  },
  // There is deliberately no `eslint` block. Next 16 removed the option along with
  // the `next lint` command, and `next build` no longer lints at all — so the
  // "lint is a separate CI step" intent that block carried is now the default and
  // saying it here is a config error rather than a preference.
};

export default config;
