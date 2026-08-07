/**
 * Typed client for the HireLens API.
 *
 * The types mirror the FastAPI response models. They are hand-written for M1;
 * generating them from the OpenAPI schema is worth doing once the shape settles.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export type MatchKind = "exact" | "whitespace_collapsed" | "whitespace_stripped";
export type RejectReason = "empty" | "too_short" | "not_found";
export type ResumeStatus =
  | "pending"
  | "processing"
  | "parsed"
  | "extracted"
  | "failed"
  | "dead_lettered";

export interface EvidenceRef {
  quote: string;
  char_start: number;
  char_end: number;
  page: number;
  match_kind: MatchKind;
  is_ambiguous: boolean;
}

export interface Claim {
  value: string;
  evidence: EvidenceRef;
}

export interface DroppedClaim {
  field: string;
  value: string;
  quote: string;
  reason: RejectReason;
}

export interface Experience {
  company: string;
  title: string;
  start: string;
  end: string;
  evidence: EvidenceRef;
}

export interface Education {
  institution: string;
  credential: string;
  evidence: EvidenceRef;
}

export interface EvidenceStats {
  verified: number;
  dropped: number;
  total_claims: number;
  hallucination_rate: number;
  attempts: number;
  by_match_kind: Partial<Record<MatchKind, number>>;
  by_reject_reason: Partial<Record<RejectReason, number>>;
}

export interface ExtractedProfile {
  full_name: Claim | null;
  headline: Claim | null;
  years_experience: Claim | null;
  seniority: string;
  seniority_evidence: EvidenceRef | null;
  skills: Claim[];
  experiences: Experience[];
  education: Education[];
  dropped: DroppedClaim[];
  stats: EvidenceStats;
}

export interface Resume {
  id: string;
  filename: string;
  status: ResumeStatus;
  size_bytes: number;
  page_count: number | null;
  /** Pages with no usable text even after OCR — nothing on them can be cited. */
  pages_without_text: number[];
  /**
   * Pages whose text was recognized from an image. A citation into one of these is
   * faithful to what was read, not necessarily to what was printed.
   */
  pages_from_ocr: number[];
  failure_reason: string | null;
  attempts: number;
  /** Whether the API would accept a retry, so this does not reimplement the rule. */
  can_retry: boolean;
}

export interface ProfileResponse {
  resume: Resume;
  profile: ExtractedProfile | null;
  document_text: string | null;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function send(path: string, init: RequestInit = {}, token?: string): Promise<Response> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    // A network-level failure is almost always "the API is not running" during
    // development, so say that rather than surfacing a bare TypeError.
    throw new ApiError(0, `Cannot reach the API at ${API_BASE}. Is it running?`);
  }

  if (!response.ok) {
    throw new ApiError(response.status, await readError(response));
  }
  return response;
}

async function request<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  return (await send(path, init, token)).json() as Promise<T>;
}

/** FastAPI returns `detail` as either a string or a list of validation errors. */
async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    const detail = body.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const first = detail[0] as { msg?: string } | undefined;
      if (first?.msg) return first.msg;
    }
  } catch {
    // Fall through to the status text.
  }
  return response.statusText || `Request failed with status ${response.status}`;
}

/**
 * `pending` means queued or waiting out a retry backoff and `processing` means a
 * worker has it; everything else is a resting state the worker has already
 * written — `extracted` on success, `failed` when the document itself cannot be
 * processed, `dead_lettered` when the retries ran out, and `parsed` when the text
 * survived but extraction did not. The reason is in `failure_reason` throughout.
 */
export function isSettled(status: ResumeStatus): boolean {
  return status !== "pending" && status !== "processing";
}

const POLL_INTERVAL_MS = 700;
const POLL_TIMEOUT_MS = 120_000;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Called with the resume every time the server reports it has changed. */
export type ProgressHandler = (resume: Resume) => void;

/**
 * Cut the byte stream back into server-sent events.
 *
 * A frame ends at a blank line; whatever follows is the start of the next one and
 * has to be held until the rest of it arrives. Lines opening with `:` are
 * keep-alive comments and carry no meaning — they exist so that proxies do not
 * drop a connection that has gone quiet.
 */
async function* readFrames(body: ReadableStream<Uint8Array>) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;
      buffer += decoder.decode(value, { stream: true });

      for (let end = buffer.indexOf("\n\n"); end !== -1; end = buffer.indexOf("\n\n")) {
        const frame = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);

        let event = "";
        let data = "";
        for (const line of frame.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) data = line.slice(5).trim();
        }
        if (event) yield { event, data };
      }
    }
  } finally {
    // Closes the connection when the caller stops reading early, and is a no-op
    // once the stream has ended on its own.
    await reader.cancel();
  }
}

export const api = {
  register: (email: string, password: string) =>
    request<TokenPair>("/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    }),

  login: (email: string, password: string) =>
    request<TokenPair>("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    }),

  refresh: (refreshToken: string) =>
    request<TokenPair>("/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    }),

  uploadResume: (file: File, token: string) => {
    const form = new FormData();
    form.append("file", file);
    return request<Resume>("/resumes", { method: "POST", body: form }, token);
  },

  listResumes: (token: string) => request<Resume[]>("/resumes", {}, token),

  /** Put a stopped resume back on the queue — the dead-letter replay path. */
  retryResume: (id: string, token: string) =>
    request<Resume>(`/resumes/${id}/retry`, { method: "POST" }, token),

  getProfile: (id: string, token: string) => request<ProfileResponse>(`/resumes/${id}`, {}, token),

  /**
   * Follow a resume over the progress stream until it reaches a resting state.
   *
   * `EventSource` would be less code, but it cannot set an `Authorization`
   * header — which leaves the token in the query string, and so in proxy access
   * logs and browser history. `fetch` keeps the bearer header and reuses the
   * error handling every other call goes through; parsing the frames is the price.
   *
   * Resolves with the settled resume, or `null` when the stream ended without one:
   * the server capped the connection, or the row is gone. The caller falls back.
   */
  async streamResume(id: string, token: string, onProgress?: ProgressHandler) {
    const response = await send(
      `/resumes/${id}/events`,
      { headers: { Accept: "text/event-stream" } },
      token,
    );
    if (!response.body) return null;

    for await (const frame of readFrames(response.body)) {
      if (frame.event === "status") onProgress?.(JSON.parse(frame.data) as Resume);
      else if (frame.event === "done") return JSON.parse(frame.data) as Resume;
      else return null; // `timeout` or `gone`
    }
    return null;
  },

  /**
   * Wait for the worker to finish with a resume, reporting each state on the way.
   *
   * Parsing and extraction happen off the request, so an upload only says the work
   * was accepted. This is the one place that waits for the rest.
   *
   * The stream is tried first — one connection, and every change as it lands.
   * Polling stays as the fallback rather than being deleted with it: a proxy that
   * buffers `text/event-stream`, or a connection the server capped, would
   * otherwise leave the page with no result at all. An `ApiError` is an answer
   * from the API itself — 401 in particular has to reach the caller, which trades
   * the refresh token for a new pair — so only a broken stream falls back.
   */
  async waitForProfile(
    id: string,
    token: string,
    onProgress?: ProgressHandler,
  ): Promise<ProfileResponse> {
    try {
      const settled = await api.streamResume(id, token, onProgress);
      if (settled) return await api.getProfile(id, token);
    } catch (caught) {
      if (caught instanceof ApiError) throw caught;
    }
    return pollForProfile(id, token, onProgress);
  },
};

/** The fallback: what the client did before the stream existed. */
async function pollForProfile(
  id: string,
  token: string,
  onProgress?: ProgressHandler,
): Promise<ProfileResponse> {
  const deadline = Date.now() + POLL_TIMEOUT_MS;
  for (;;) {
    const response = await api.getProfile(id, token);
    onProgress?.(response.resume);
    if (isSettled(response.resume.status)) return response;
    if (Date.now() >= deadline) {
      throw new ApiError(0, "Still processing after two minutes. Try again in a moment.");
    }
    await sleep(POLL_INTERVAL_MS);
  }
}
