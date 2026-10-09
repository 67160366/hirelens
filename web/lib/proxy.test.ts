import { afterEach, describe, expect, it, vi } from "vitest";
import config from "../next.config";

afterEach(() => vi.unstubAllEnvs());

describe("API proxy", () => {
  it("keeps existing local deployments without a proxy", async () => {
    vi.stubEnv("API_PROXY_BASE", undefined);
    expect(await config.rewrites?.()).toEqual([]);
  });

  it("serves the API on the web origin", async () => {
    vi.stubEnv("API_PROXY_BASE", "https://hirelens-api.onrender.com");
    expect(await config.rewrites?.()).toEqual([
      { source: "/api/:path*", destination: "https://hirelens-api.onrender.com/:path*" },
    ]);
  });

  it.each([
    "http://hirelens-api.onrender.com",
    "https://user:secret@hirelens-api.onrender.com",
    "https://hirelens-api.onrender.com/extra",
    "https://hirelens-api.onrender.com?token=secret",
  ])("refuses an invalid upstream %s", async (upstream) => {
    vi.stubEnv("API_PROXY_BASE", upstream);
    await expect(config.rewrites?.()).rejects.toThrow("API_PROXY_BASE");
  });
});
