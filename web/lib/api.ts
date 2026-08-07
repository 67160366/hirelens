/**
 * Typed client for the HireLens API.
 *
 * The types mirror the FastAPI response models. They are hand-written for M1;
 * generating them from the OpenAPI schema is worth doing once the shape settles.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export type MatchKind = "exact" | "whitespace_collapsed" | "whitespace_stripped";
export type RejectReason = "empty" | "too_short" | "not_found";
export type ResumeStatus = "pending" | "parsed" | "extracted" | "failed";

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
  pages_without_text: number[];
  failure_reason: string | null;
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

async function request<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
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
  return (await response.json()) as T;
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
 * `pending` means queued or running; everything else is a resting state the
 * worker has already written — `extracted` on success, `failed` when parsing
 * gave up, and `parsed` when the text survived but extraction did not (the
 * failure is in `failure_reason` either way).
 */
export function isSettled(status: ResumeStatus): boolean {
  return status !== "pending";
}

const POLL_INTERVAL_MS = 700;
const POLL_TIMEOUT_MS = 120_000;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

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

  getProfile: (id: string, token: string) => request<ProfileResponse>(`/resumes/${id}`, {}, token),

  /**
   * Poll until the worker has finished with a resume.
   *
   * Parsing and extraction moved off the request, so an upload only tells us the
   * work was accepted. Polling is the placeholder: M2 #3 replaces it with an SSE
   * progress stream, which is why the waiting lives behind one function.
   */
  async waitForProfile(id: string, token: string): Promise<ProfileResponse> {
    const deadline = Date.now() + POLL_TIMEOUT_MS;
    for (;;) {
      const response = await api.getProfile(id, token);
      if (isSettled(response.resume.status)) return response;
      if (Date.now() >= deadline) {
        throw new ApiError(0, "Still processing after two minutes. Try again in a moment.");
      }
      await sleep(POLL_INTERVAL_MS);
    }
  },
};
