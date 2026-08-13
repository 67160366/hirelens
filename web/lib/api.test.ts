/**
 * Tests for the SSE frame parser.
 *
 * `readFrames` is the first real logic on the client: it parses a wire format and
 * has to buffer across chunk boundaries, because the server decides where a TCP
 * chunk ends and a frame can be cut anywhere. Nothing pinned it before, and the
 * failure mode is quiet — a dropped frame just looks like a resume that never
 * finished, which is indistinguishable from a slow worker.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { api, readFrames } from "./api";

/** A body that hands back exactly the chunks given, as the network would. */
function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

async function collect(...chunks: string[]) {
  const frames = [];
  for await (const frame of readFrames(streamOf(...chunks))) frames.push(frame);
  return frames;
}

describe("readFrames", () => {
  it("reads a whole frame", async () => {
    expect(await collect('event: status\ndata: {"status":"pending"}\n\n')).toEqual([
      { event: "status", data: '{"status":"pending"}' },
    ]);
  });

  it("reads several frames from one chunk", async () => {
    const frames = await collect(
      'event: status\ndata: {"status":"processing"}\n\n' +
        'event: done\ndata: {"status":"extracted"}\n\n',
    );
    expect(frames.map((f) => f.event)).toEqual(["status", "done"]);
  });

  it("joins a frame split across chunks", async () => {
    // The case that motivated this file: the server picks the chunk boundary,
    // and it can fall anywhere — including mid-token.
    const frames = await collect('event: sta', 'tus\ndata: {"sta', 'tus":"pending"}\n\n');
    expect(frames).toEqual([{ event: "status", data: '{"status":"pending"}' }]);
  });

  it("joins a frame split exactly on the blank-line separator", async () => {
    // The nastiest boundary: "\n\n" itself arrives in two pieces, so a naive
    // indexOf on each chunk alone would never see the terminator.
    const frames = await collect('event: done\ndata: {"ok":true}\n', '\n');
    expect(frames).toEqual([{ event: "done", data: '{"ok":true}' }]);
  });

  it("ignores keep-alive comments between frames", async () => {
    // The server sends `: keep-alive` when nothing has changed, so a quiet stream
    // is not mistaken for a dead connection.
    const frames = await collect(
      ": keep-alive\n\n",
      'event: status\ndata: {"status":"processing"}\n\n',
      ": keep-alive\n\n",
    );
    expect(frames).toEqual([{ event: "status", data: '{"status":"processing"}' }]);
  });

  it("drops a frame with no event name", async () => {
    // Bare `data:` frames are not part of this API's contract, and yielding one
    // would reach a caller that switches on `frame.event`.
    expect(await collect('data: {"status":"pending"}\n\n')).toEqual([]);
  });

  it("ignores a trailing partial frame rather than yielding half of it", async () => {
    // A capped or dropped connection must not deliver a truncated payload —
    // `JSON.parse` downstream would throw on it.
    const frames = await collect(
      'event: status\ndata: {"status":"pending"}\n\n',
      "event: done\ndata: {\"stat",
    );
    expect(frames).toEqual([{ event: "status", data: '{"status":"pending"}' }]);
  });

  it("yields nothing for an empty stream", async () => {
    expect(await collect()).toEqual([]);
  });

  it("survives a multi-byte character split across chunks", async () => {
    // Thai is the whole point of this project, and a UTF-8 code point can be cut
    // in half by a chunk boundary. The streaming TextDecoder is what holds the
    // partial bytes; this proves it is actually being used that way.
    const encoder = new TextEncoder();
    const payload = encoder.encode('event: status\ndata: {"name":"สมชาย"}\n\n');
    const cut = 30; // lands inside one of the Thai characters
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(payload.slice(0, cut));
        controller.enqueue(payload.slice(cut));
        controller.close();
      },
    });

    const frames = [];
    for await (const frame of readFrames(stream)) frames.push(frame);
    expect(frames).toEqual([{ event: "status", data: '{"name":"สมชาย"}' }]);
  });
});

/**
 * The other place a status code carries meaning rather than just success.
 *
 * `POST /jobs/{id}/screenings` answers **202** when it queued a model call and
 * **200** when the stored result already answers the question. Every other call on
 * this client throws away the status, so this one has to be pinned: collapse the
 * two and the UI silently stops being able to tell anyone when it spent money.
 */
describe("createScreening", () => {
  function respondWith(status: number) {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ id: "s1", status: "pending" }), { status })),
    );
  }

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reports 202 as work that was queued and billed", async () => {
    respondWith(202);
    const { queued } = await api.createScreening("job-1", "resume-1", "token");
    expect(queued).toBe(true);
  });

  it("reports 200 as an answer that already existed", async () => {
    respondWith(200);
    const { queued } = await api.createScreening("job-1", "resume-1", "token");
    expect(queued).toBe(false);
  });

  it("returns the screening either way", async () => {
    respondWith(200);
    const { screening } = await api.createScreening("job-1", "resume-1", "token");
    expect(screening.id).toBe("s1");
  });
});

/**
 * Consent travels with the upload, and it travels as what the box actually says.
 *
 * The tempting version hard-codes `"true"` — the server requires it, after all,
 * so why send anything else. That turns a consent field into a formality: the
 * checkbox could be unticked and the upload would still assert agreement. What
 * makes it mean something is that the value is the user's answer, so an unticked
 * box produces an upload the server refuses.
 */
describe("uploadResume", () => {
  function capture() {
    const sent: FormData[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init: RequestInit) => {
        sent.push(init.body as FormData);
        return new Response(JSON.stringify({ id: "r1" }), { status: 201 });
      }),
    );
    return sent;
  }

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  async function uploadWith(consent: boolean): Promise<FormData> {
    const sent = capture();
    await api.uploadResume(new File(["%PDF-"], "cv.pdf"), "token", consent);
    const body = sent[0];
    expect(body).toBeDefined();
    return body as FormData;
  }

  it("sends the file and the consent together", async () => {
    const body = await uploadWith(true);
    expect(body.get("consent")).toBe("true");
    expect((body.get("file") as File).name).toBe("cv.pdf");
  });

  it("sends false when the box is not ticked, rather than asserting agreement", async () => {
    const body = await uploadWith(false);
    expect(body.get("consent")).toBe("false");
  });
});

/**
 * Every write that carries a JSON body must say so.
 *
 * Starlette decides whether to parse a body by its `Content-Type`. Without the
 * header the body arrives as a *string*, pydantic answers 422 — "Input should be
 * a valid dictionary or object to extract fields from" — and the UI shows that
 * sentence to a person who has done nothing wrong.
 *
 * `moveApplication` hand-built its `RequestInit` instead of going through
 * `json()`, so **every** application transition failed: shortlist, reject and
 * withdraw. Found by clicking Shortlist in a browser; no test looked, because the
 * 13 cases covering `lib/applications.ts` test the pure logic and never the wiring.
 *
 * This is a table rather than one case about one call, so the next write to skip
 * the helper fails here rather than in front of a user.
 */
describe("every JSON write sets Content-Type", () => {
  function captureInit() {
    const sent: RequestInit[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init: RequestInit) => {
        sent.push(init);
        return new Response(JSON.stringify({}), { status: 200 });
      }),
    );
    return sent;
  }

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const writes: [string, () => Promise<unknown>][] = [
    ["moveApplication", () => api.moveApplication("a1", "shortlisted", "token")],
    ["moveApplication with a reason", () => api.moveApplication("a1", "rejected", "token", "no")],
    ["applyToJob", () => api.applyToJob("j1", "r1", "token")],
    ["createJob", () => api.createJob({ title: "t", description: null, requirements: [] }, "token")],
    ["createScreening", () => api.createScreening("j1", "r1", "token")],
    ["register", () => api.register("a@example.com", "a-good-password")],
    ["login", () => api.login("a@example.com", "a-good-password")],
  ];

  it.each(writes)("%s", async (_name, call) => {
    const sent = captureInit();
    await call();

    const init = sent[0];
    expect(init).toBeDefined();
    expect(typeof init?.body).toBe("string");
    const headers = new Headers(init?.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
  });
});

/**
 * Registration carries the role, because there is no other way to become one.
 *
 * `SelfServiceRole` has been a registration field on the server since M4 slice 2 —
 * "there is no other way to become a recruiter" is the reason it exists — and this
 * client sent only `{email, password}`. So a browser could produce nothing but
 * candidates, and every recruiter screen was unreachable without going around the
 * UI with curl. The server was right and the client never asked.
 *
 * The default matters as much as the field: an omitted role must mean `candidate`,
 * never `recruiter`.
 */
describe("register", () => {
  function captureBody() {
    const sent: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init: RequestInit) => {
        sent.push(JSON.parse(String(init.body)));
        return new Response(JSON.stringify({}), { status: 201 });
      }),
    );
    return sent;
  }

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends the role it was given", async () => {
    const sent = captureBody();
    await api.register("hirer@example.com", "a-good-password", "recruiter");
    expect(sent[0]).toMatchObject({ email: "hirer@example.com", role: "recruiter" });
  });

  it("defaults to candidate rather than omitting the field", async () => {
    const sent = captureBody();
    await api.register("seeker@example.com", "a-good-password");
    // Omitting it would let the server's own default decide, which happens to
    // agree — but the request should say what it means, and a silent omission is
    // how the field went missing in the first place.
    expect(sent[0]).toMatchObject({ role: "candidate" });
  });
});
