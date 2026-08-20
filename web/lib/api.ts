/**
 * Typed client for the HireLens API.
 *
 * The types mirror the FastAPI response models. They are hand-written for M1;
 * generating them from the OpenAPI schema is worth doing once the shape settles.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export type MatchKind = "exact" | "whitespace_collapsed" | "whitespace_stripped";
/** `unknown_requirement` is judging's: a quote aimed at a requirement that does not exist. */
export type RejectReason = "empty" | "too_short" | "not_found" | "unknown_requirement";
export type ResumeStatus =
  "pending" | "processing" | "parsed" | "extracted" | "failed" | "dead_lettered";

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

export interface ConsentTerms {
  version: string;
  text: string;
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

/**
 * Consecutive characters sharing a line, with a box per character (M5 slice 4).
 *
 * `x` holds one `[x0, x1]` pair per character starting at `char_start`, and `top` /
 * `bottom` are shared because every character in a run has them by definition. Runs
 * rather than words: Thai has no spaces, so a whitespace "word" can be an unbroken
 * 31-character run with real quotes inside it.
 */
export interface CharRun {
  char_start: number;
  top: number;
  bottom: number;
  x: [number, number][];
}

/** One page's characters, and the page box they were measured against. */
export interface PageGeometry {
  page_number: number;
  width: number;
  height: number;
  runs: CharRun[];
}

export interface GeometryReport {
  /**
   * False for a resume parsed before migration `0010`, which is not backfilled.
   * Deliberately distinct from `pages` being empty, which means the parser looked
   * and could prove nothing — the overlay says which, so a fallback is never silent.
   */
  measured: boolean;
  /** Sparse: a page is absent when its geometry could not be proven consistent. */
  pages: PageGeometry[];
  /** Carried here because `ScreeningDetail` has no `Resume` to read it off. */
  pages_from_ocr: number[];
}

export type Role = "candidate" | "recruiter" | "admin";

/**
 * The roles an account may claim for itself, mirroring `SelfServiceRole`.
 *
 * `admin` is deliberately absent — an account that can grant itself admin is not a
 * role system, and the server refuses it with a 422 from the schema. Keeping the
 * narrower type here means the client cannot even ask.
 */
export type SelfServiceRole = Exclude<Role, "admin">;

export interface Account {
  id: string;
  email: string;
  display_name: string | null;
  /** Which routes this account may reach. Read from the row on every request, not
   * carried in the token, so a change takes effect immediately. */
  role: Role;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

/* -------------------------------------------------------------------------- */
/* M3: jobs, screenings and ranking                                            */
/* -------------------------------------------------------------------------- */

export type ApplicationState =
  "applied" | "screening" | "screened" | "shortlisted" | "rejected" | "withdrawn";

export interface Application {
  id: string;
  job_id: string;
  job_title: string;
  candidate_id: string;
  resume_id: string;
  /** Served by the API, not joined from `GET /resumes` — that returns the caller's
   * own, which stopped covering the list the moment somebody else could apply. */
  resume_filename: string;
  /** Served for the same reason, and needed for the same screen: a recruiter may
   * screen this resume but cannot list it, so without this there is no way to tell
   * one that can be screened from one that would raise `NotScreenable`. Applying
   * does not require an extracted resume, so it is a real question. */
  resume_status: ResumeStatus;
  state: ApplicationState;
  created_at: string;
}

export interface ApplicationEvent {
  id: string;
  position: number;
  from_state: ApplicationState | null;
  to_state: ApplicationState;
  /** Null means the system moved it — a worker following a screening is not a
   * person, and the UI must not draw one. */
  actor_id: string | null;
  actor_role: Role | null;
  reason: string | null;
  /** What the move rested on, where it rested on anything. */
  screening_id: string | null;
  note: string | null;
  created_at: string;
}

export type RequirementKind = "skill" | "experience" | "education" | "language" | "other";

/** Mirrors `RequirementOut` in `api/app/api/routes/jobs.py`. */
export interface Requirement {
  id: string;
  position: number;
  kind: RequirementKind;
  label: string;
  detail: string | null;
  /** A hard gate in ranking, not a heavy weight: missing one ranks below everyone who has them all. */
  must_have: boolean;
  weight: number;
}

/** Where a posting is in its editorial life — see `api/app/publication.py`. */
export type JobStatus = "draft" | "published" | "closed";

export interface Job {
  id: string;
  title: string;
  description: string | null;
  location: string | null;
  /** `draft` until an **admin** publishes it. A recruiter cannot: anyone can
   *  register as one, so publishing is deliberately not self-grantable. */
  status: JobStatus;
  /** When it first appeared publicly, or null while it never has. */
  published_at: string | null;
  requirements: Requirement[];
}

/** The whole job in one call, which is how a posting is usually authored. */
export interface JobInput {
  title: string;
  description?: string | null;
  requirements?: RequirementInput[];
}

export interface RequirementInput {
  kind: RequirementKind;
  label: string;
  detail?: string | null;
  must_have: boolean;
  weight: number;
}

/** Every field optional: unset means "leave alone", and `detail: null` clears it. */
export type RequirementPatch = Partial<RequirementInput>;

/** `api/app/api/routes/jobs.py` — the whole requirement list travels in one prompt. */
export const MAX_REQUIREMENTS_PER_JOB = 30;

/**
 * There is no `not_met`, on purpose.
 *
 * Absence cannot be quoted — you cannot cite text that is not in a document — so
 * "not met" would be the one unverifiable assertion this project exists to refuse.
 * `not_evidenced` is also the honest label: the system cannot tell "the candidate
 * lacks it" from "the resume does not mention it". See docs/HANDOFF.md §5.
 */
export type Verdict = "met" | "not_evidenced";

export interface RequirementJudgment {
  requirement_id: string;
  label: string;
  must_have: boolean;
  weight: number;
  verdict: Verdict;
  /** Empty exactly when the verdict is `not_evidenced` — the verdict is derived from this. */
  evidence: EvidenceRef[];
}

export type ScreeningStatus =
  "pending" | "processing" | "completed" | "failed" | "dead_lettered";

/** Mirrors `ScreeningOut` in `api/app/api/routes/screenings.py`. */
export interface Screening {
  id: string;
  job_id: string;
  resume_id: string;
  status: ScreeningStatus;
  failure_reason: string | null;
  attempts: number;
  can_retry: boolean;

  requirements_met: number;
  requirements_total: number;
  claims_verified: number;
  claims_dropped: number;
  hallucination_rate: number;

  /**
   * The requirements or the judging prompt changed after this ran, so it answers a
   * question nobody is asking any more. Reported rather than silently re-run,
   * because re-running costs a model call.
   */
  is_stale: boolean;
}

export interface ScreeningDetail {
  screening: Screening;
  /**
   * The stored `Judgment` verbatim, with `must_have` and `weight` **frozen at
   * judging time**. Ranking re-keys both against the job's current requirements, so
   * render verdicts from a `RankedEntry` and use this route for `document_text`.
   *
   * `dropped` and `stats` are the exception, and safely so: ranking re-keys nothing
   * about them and `RankedEntry` does not carry them at all. They are facts about
   * the judging call that produced this row — what the model claimed and could not
   * cite — and no weight edit can make them go out of date.
   */
  judgment: {
    requirements?: RequirementJudgment[];
    dropped?: DroppedClaim[];
    stats?: EvidenceStats;
  } | null;
  document_text: string | null;
}

export type ExclusionReason = "stale" | "not_completed" | "malformed";

export interface ExcludedEntry {
  screening_id: string;
  resume_id: string;
  resume_filename: string | null;
  status: string;
  reason: ExclusionReason;
}

export interface RankedEntry {
  rank: number;
  screening_id: string;
  resume_id: string;
  /** Served, not joined. `GET /resumes` returns only the caller's own uploads, so a
   * client-side join is true right up until an application puts somebody else's
   * resume in the ranking — which `api/app/schemas/ranking.py` says on the field. Null
   * where the row is gone, and a null must never be turned into a made-up name. */
  resume_filename: string | null;
  /** Every `must_have` requirement is met. A gate, not a score contribution. */
  gate_passed: boolean;
  /** Weighted share of requirements met, in [0, 1]. Orders *within* a tier only. */
  score: number;
  must_haves_met: number;
  must_haves_total: number;
  requirements_met: number;
  requirements_total: number;
  /** The rationale, not a promise: every requirement with its verdict and citations. */
  requirements: RequirementJudgment[];
}

export interface Ranking {
  ranked: RankedEntry[];
  /** Nothing is dropped silently — a screening that could not be ranked says why. */
  excluded: ExcludedEntry[];
}

/** Which piece of work paid for a model call (M5 slice 2). */
export type CallBucket = "extraction" | "judging" | "unattributed" | "ambiguous";

/** Whose rows a usage report covers. `all` is ADMIN only. */
export type UsageScope = "own" | "all";

export interface CallTotals {
  /** How many rows produced every figure here — the citation for the numbers. */
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cached_input_tokens: number;
  latency_ms_total: number;
  /** Null when there are no calls: the mean of zero samples is not zero. */
  latency_ms_mean: number | null;
  /** How many of `calls` carry a known price, so a reader can see why cost is null. */
  calls_priced: number;
  /**
   * Null unless **every** call in the group is priced. A partial sum would look
   * complete and be wrong, which is the hazard `cost_usd`'s nullability exists for.
   */
  cost_usd: number | null;
}

export interface CallGroup {
  provider: string;
  model: string;
  prompt_version: string;
  bucket: CallBucket;
  totals: CallTotals;
}

export interface QualitySummary {
  profiles: number;
  claims_verified: number;
  claims_dropped: number;
  /** Recomputed from the totals, not the mean of the per-profile rates. */
  hallucination_rate: number | null;
  extraction_attempts_total: number;
}

export interface ParseOutcome {
  status: ResumeStatus;
  resumes: number;
}

export interface UsageReport {
  scope: UsageScope;
  generated_at: string;
  totals: CallTotals;
  /** Every bucket is present, including the empty ones. */
  by_bucket: Record<CallBucket, CallTotals>;
  by_group: CallGroup[];
  quality: QualitySummary;
  parse_outcomes: ParseOutcome[];
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

/**
 * Every request this client makes, and the only `fetch` in the app.
 *
 * **`credentials: "include"` is the authentication.** The API issues the session as
 * httpOnly cookies, so there is no token here to attach and nothing for an XSS
 * payload on this page to steal — the browser carries the credential and never shows
 * it to script. It has to be set explicitly on every call because the default is
 * `same-origin` and the API is a different origin (`:8000` to the page's `:3000`).
 *
 * Note what "different origin" is not: cookies ignore ports, so `localhost:3000` and
 * `localhost:8000` are the same *site* and `SameSite=Lax` sends the cookie between
 * them. `127.0.0.1:3000` is a different site and it does not, which is measured
 * rather than assumed and is why `auth.establishSession` checks that the session
 * survived signing in.
 */
async function send(path: string, init: RequestInit = {}): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, credentials: "include" });
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

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  return (await send(path, init)).json() as Promise<T>;
}

/** A JSON request body, which every write on this API except the upload takes. */
function json(method: string, payload: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  };
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

/**
 * The same question for a screening, which has its own status vocabulary.
 *
 * `Screening` and `Resume` deliberately do not share an enum — a screening is never
 * `parsed` or `extracted`. What they share is the retry policy, and that is shared
 * as a function on the server rather than by making two tables wear one vocabulary
 * (docs/HANDOFF.md §5).
 */
export function isScreeningSettled(status: ScreeningStatus): boolean {
  return status !== "pending" && status !== "processing";
}

export const POLL_INTERVAL_MS = 700;
export const POLL_TIMEOUT_MS = 120_000;

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
/**
 * Exported for `lib/api.test.ts`, not for callers. It is the only wire-format
 * parser on this side — a frame can be split across chunks, and keep-alive
 * comments arrive between them — so it is worth pinning directly rather than
 * through a mocked `fetch`.
 */
export async function* readFrames(body: ReadableStream<Uint8Array>) {
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
  /** Create an account. `role` is a registration field because there is no other way
   * to become a recruiter — `SelfServiceRole` on the server omits `admin`, which is
   * granted out of band. Sending it was the missing half: the server has taken a
   * role since M4 slice 2 and this client never offered one, so a browser could
   * only ever produce candidates and the recruiter half of the UI was unreachable
   * without curl. */
  register: (email: string, password: string, role: SelfServiceRole = "candidate") =>
    request<TokenPair>("/auth/register", json("POST", { email, password, role })),

  login: (email: string, password: string) =>
    request<TokenPair>("/auth/login", json("POST", { email, password })),

  /** Rotate the session. **No body**: the refresh token is an httpOnly cookie the
   * browser attaches and this page is not allowed to read, which is the point of it
   * being httpOnly. Sending `{}` would not do — the server would validate it against
   * a schema requiring the token and answer 422 before it ever looked at the cookie. */
  refresh: () => request<TokenPair>("/auth/refresh", { method: "POST" }),

  /** End this session on the server, not merely in this tab. Without it a sign-out
   * would leave the refresh token mintable for another fortnight — the hole
   * `/auth/logout` exists to close, and the cookie client is the one that cannot
   * send the token in a body to close it itself. */
  logout: async (): Promise<void> => {
    await send("/auth/logout", { method: "POST" });
  },

  /** The wording an upload's `consent` agrees to. Unauthenticated, so it can be
   * shown before anyone has an account — and fetched rather than duplicated here,
   * so what somebody agreed to and what they were shown cannot drift apart. */
  getConsent: () => request<ConsentTerms>("/resumes/consent", {}),

  uploadResume: (file: File, consent: boolean) => {
    const form = new FormData();
    form.append("file", file);
    // Required by the server since M4 slice 4, and sent as what the box actually
    // says rather than a hard-coded "true": a client that always sends true has
    // turned a consent field into a formality.
    form.append("consent", String(consent));
    return request<Resume>("/resumes", { method: "POST", body: form });
  },

  listResumes: () => request<Resume[]>("/resumes", {}),

  /** Put a stopped resume back on the queue — the dead-letter replay path. */
  retryResume: (id: string) => request<Resume>(`/resumes/${id}/retry`, { method: "POST" }),

  getProfile: (id: string) => request<ProfileResponse>(`/resumes/${id}`, {}),

  /**
   * The original bytes, fetched rather than handed to pdf.js as a URL.
   *
   * The reason has outlived the bearer token it was written about. It used to be
   * that a URL handed to pdf.js would put the token in the query string, and so in
   * proxy access logs and browser history; the session is a cookie now and would
   * travel fine. What still holds is the rest of it: fetching keeps the `ApiError`
   * taxonomy and the 401-renew-and-retry path, which a URL pdf.js opens itself
   * would bypass entirely — a expired session would render a broken viewer instead
   * of renewing.
   */
  getResumeFile: async (id: string): Promise<ArrayBuffer> =>
    (await send(`/resumes/${id}/file`, {})).arrayBuffer(),

  /** Where each character of the document sits, for the overlay to draw. */
  getResumeGeometry: (id: string) => request<GeometryReport>(`/resumes/${id}/geometry`, {}),

  /* ---------------------------------------------------------------------- */
  /* Jobs and their requirements                                             */
  /* ---------------------------------------------------------------------- */

  /** The signed-in account, including its role — which is what lets the UI show a
   * candidate their applications and a recruiter their postings, instead of
   * offering both and letting one of them 403. */
  me: () => request<Account>("/auth/me", {}),

  listJobs: () => request<Job[]>("/jobs", {}),

  /* ---------------------------------------------------------------------- */
  /* Applications                                                            */
  /* ---------------------------------------------------------------------- */

  /** Apply to a job. 201 when created, 200 when you had already applied — the
   * natural key carrying the idempotency, so calling it twice is safe. */
  applyToJob: (jobId: string, resumeId: string) =>
    request<Application>(`/jobs/${jobId}/applications`, json("POST", { resume_id: resumeId })),

  listJobApplications: (jobId: string) =>
    request<Application[]>(`/jobs/${jobId}/applications`, {}),

  listMyApplications: () => request<Application[]>("/me/applications", {}),

  /** Move an application. The server answers **409 with the reason** when the move
   * is not allowed, which surfaces here as an `ApiError` carrying that sentence —
   * it is written for a person to read, so show it rather than replacing it.
   *
   * Goes through `json()` like every other write. Hand-building the `RequestInit`
   * here omitted `Content-Type`, so the body was never parsed as JSON and the
   * server answered 422 to *every* transition — shortlist, reject and withdraw
   * alike — with a pydantic message shown to the user verbatim. */
  moveApplication: (applicationId: string, toState: ApplicationState, reason?: string) =>
    request<Application>(
      `/applications/${applicationId}/transitions`,
      json("POST", { to_state: toState, reason: reason ?? null }),
    ),

  listApplicationEvents: (applicationId: string) =>
    request<ApplicationEvent[]>(`/applications/${applicationId}/events`, {}),

  getJob: (id: string) => request<Job>(`/jobs/${id}`, {}),

  /** Title, description and the whole requirement list in one call. */
  createJob: (payload: JobInput) => request<Job>("/jobs", json("POST", payload)),

  deleteJob: async (id: string): Promise<void> => {
    await send(`/jobs/${id}`, { method: "DELETE" });
  },

  addRequirement: (jobId: string, payload: RequirementInput) =>
    request<Requirement>(`/jobs/${jobId}/requirements`, json("POST", payload)),

  /**
   * Change one requirement.
   *
   * Which fields moved decides what it costs: `must_have` and `weight` are excluded
   * from the screening fingerprint, so editing them reorders the ranking for free.
   * `kind`, `label` and `detail` are what the judge was shown, so editing one makes
   * every existing screening stale. `staleningFields` names the difference.
   */
  updateRequirement: (jobId: string, requirementId: string, patch: RequirementPatch) =>
    request<Requirement>(`/jobs/${jobId}/requirements/${requirementId}`, json("PATCH", patch)),

  deleteRequirement: async (jobId: string, requirementId: string): Promise<void> => {
    await send(`/jobs/${jobId}/requirements/${requirementId}`, { method: "DELETE" });
  },

  /* ---------------------------------------------------------------------- */
  /* Screenings and the ranking they feed                                    */
  /* ---------------------------------------------------------------------- */

  /**
   * Screen one resume against one job.
   *
   * Answers **202** when it queued work — one model call, billed — and **200** when
   * the stored result already answers the question. That distinction is the whole
   * reason this does not go through `request`: a caller has to be able to tell the
   * user whether it just spent anything.
   */
  async createScreening(
    jobId: string,
    resumeId: string,
  ): Promise<{ screening: Screening; queued: boolean }> {
    const response = await send(
      `/jobs/${jobId}/screenings`,
      json("POST", { resume_id: resumeId }),
    );
    return {
      screening: (await response.json()) as Screening,
      queued: response.status === 202,
    };
  },

  /** The raw list, including the ones still running and the ones that failed. */
  listScreenings: (jobId: string) => request<Screening[]>(`/jobs/${jobId}/screenings`, {}),

  getScreening: (id: string) => request<ScreeningDetail>(`/screenings/${id}`, {}),

  retryScreening: (id: string) =>
    request<Screening>(`/screenings/${id}/retry`, { method: "POST" }),

  /**
   * The ordered answer, computed on read.
   *
   * Costs one query and no model call, which is what lets a weight edit reorder the
   * list immediately while every screening stays current. Re-fetch it freely.
   */
  getRanking: (jobId: string) => request<Ranking>(`/jobs/${jobId}/ranking`, {}),

  /**
   * What this account's model calls consumed, and how well the guardrail held.
   *
   * Reports; never re-asks. Every figure is a query over rows the system already
   * wrote, so refreshing this screen costs a query and **never a model call**.
   */
  getUsage: () => request<UsageReport>("/metrics/usage", {}),

  /**
   * Follow a resume over the progress stream until it reaches a resting state.
   *
   * `EventSource` was refused because it cannot set an `Authorization` header,
   * which would have left the token in the query string and so in proxy access logs
   * and browser history. **That objection is gone** — the session is a cookie and
   * `EventSource` sends cookies with `withCredentials`. It stays on `fetch` anyway,
   * for the reason that outlived the first: `EventSource` reports every failure as
   * one opaque `error` event, so a 401 could not reach `authorized` to be renewed
   * and a stream would simply stop. Parsing the frames is what buys that.
   *
   * Resolves with the settled resume, or `null` when the stream ended without one:
   * the server capped the connection, or the row is gone. The caller falls back.
   */
  async streamResume(id: string, onProgress?: ProgressHandler) {
    const response = await send(`/resumes/${id}/events`, {
      headers: { Accept: "text/event-stream" },
    });
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
  async waitForProfile(id: string, onProgress?: ProgressHandler): Promise<ProfileResponse> {
    try {
      const settled = await api.streamResume(id, onProgress);
      if (settled) return await api.getProfile(id);
    } catch (caught) {
      if (caught instanceof ApiError) throw caught;
    }
    return pollForProfile(id, onProgress);
  },
};

/** The fallback: what the client did before the stream existed. */
async function pollForProfile(
  id: string,
  onProgress?: ProgressHandler,
): Promise<ProfileResponse> {
  const deadline = Date.now() + POLL_TIMEOUT_MS;
  for (;;) {
    const response = await api.getProfile(id);
    onProgress?.(response.resume);
    if (isSettled(response.resume.status)) return response;
    if (Date.now() >= deadline) {
      throw new ApiError(0, "Still processing after two minutes. Try again in a moment.");
    }
    await sleep(POLL_INTERVAL_MS);
  }
}
