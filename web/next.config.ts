import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  eslint: {
    // Lint is a separate CI step; a lint warning should not fail the build.
    ignoreDuringBuilds: true,
  },
};

export default config;
