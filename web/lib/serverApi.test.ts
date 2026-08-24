import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchPosting, serverApiBase } from "./serverApi";

const original = { ...process.env };

afterEach(() => {
  process.env = { ...original };
  vi.unstubAllGlobals();
});

describe("serverApiBase", () => {
  // The whole reason this module exists: inside the `web` container the public
  // base points at the container itself, so the server needs its own address.
  it("prefers the server-side address when there is one", () => {
    process.env.SERVER_API_BASE = "http://api:8000";
    process.env.NEXT_PUBLIC_API_BASE = "http://localhost:8000";
    expect(serverApiBase()).toBe("http://api:8000");
  });

  // On a developer's machine the two really are the same address, and requiring
  // the extra variable there would make `npm run dev` need configuration it never
  // needed before.
  it("falls back to the public address when it is not set", () => {
    delete process.env.SERVER_API_BASE;
    process.env.NEXT_PUBLIC_API_BASE = "http://localhost:8000";
    expect(serverApiBase()).toBe("http://localhost:8000");
  });

  it("has a working default with neither set", () => {
    delete process.env.SERVER_API_BASE;
    delete process.env.NEXT_PUBLIC_API_BASE;
    expect(serverApiBase()).toBe("http://localhost:8000");
  });

  it("refuses to answer in a browser, where its address means nothing", () => {
    vi.stubGlobal("window", {});
    expect(() => serverApiBase()).toThrow(/server-only/);
  });
});

describe("fetchPosting", () => {
  // The distinction the soft 404 was hiding: a posting that is not public and an
  // API that cannot be reached are different answers, and the page does different
  // things with them — one is a real 404, the other renders and retries from the
  // browser.
  it("reports a 404 as missing", async () => {
    vi.stubGlobal("fetch", async () => new Response("", { status: 404 }));
    expect(await fetchPosting("p1")).toEqual({ found: false, reason: "missing" });
  });

  it("reports a refused connection as unreachable", async () => {
    vi.stubGlobal("fetch", async () => {
      throw new TypeError("fetch failed");
    });
    expect(await fetchPosting("p1")).toEqual({ found: false, reason: "unreachable" });
  });

  it("reports a 500 as unreachable rather than as a missing posting", async () => {
    vi.stubGlobal("fetch", async () => new Response("", { status: 500 }));
    expect(await fetchPosting("p1")).toEqual({ found: false, reason: "unreachable" });
  });

  it("returns the posting when there is one", async () => {
    vi.stubGlobal(
      "fetch",
      async () => new Response(JSON.stringify({ id: "p1", title: "Backend" }), { status: 200 }),
    );
    const lookup = await fetchPosting("p1");
    expect(lookup.found && lookup.posting.title).toBe("Backend");
  });

  it("escapes the id rather than pasting it into the path", async () => {
    let seen = "";
    vi.stubGlobal("fetch", async (url: string) => {
      seen = url;
      return new Response("", { status: 404 });
    });
    await fetchPosting("../resumes");
    expect(seen).toContain("%2F");
  });
});
