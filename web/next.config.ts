import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // Emit a self-contained server bundle with only the dependencies actually
  // reached, so the runtime image needs no node_modules at all. Without this the
  // image has to carry the full dev tree — Next 15 pulls in sharp and the whole
  // TypeScript toolchain, none of which a running server uses.
  output: "standalone",
  eslint: {
    // Lint is a separate CI step; a lint warning should not fail the build.
    ignoreDuringBuilds: true,
  },
};

export default config;
