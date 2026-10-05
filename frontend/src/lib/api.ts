import { createClient } from "@/lib/supabase";
import { DEMO_JOB_ID, DEMO_IDEA, DEMO_CLAIMS, DEMO_EVIDENCE } from "@/lib/demo";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

async function authHeaders(
  jwt?: string,
  signal?: AbortSignal,
): Promise<Record<string, string>> {
  // Supabase session refresh has no AbortSignal API. Stop waiting on cancellation
  // so a late session response cannot launch an obsolete paid request.
  if (signal?.aborted)
    throw Object.assign(new Error("Request cancelled."), {
      name: "AbortError",
    });
  const session = createClient().auth.getSession();
  const { data, error } = await new Promise<Awaited<typeof session>>(
    (resolve, reject) => {
      const abort = () =>
        reject(
          Object.assign(new Error("Request cancelled."), {
            name: "AbortError",
          }),
        );
      if (signal?.aborted) {
        abort();
        return;
      }
      signal?.addEventListener("abort", abort, { once: true });
      session
        .then(resolve, reject)
        .finally(() => signal?.removeEventListener("abort", abort));
    },
  );
  const token = jwt ?? data.session?.access_token;
  if (error || !token)
    throw Object.assign(
      new Error(
        "Sign in to access private analyses, or view the synthetic demo.",
      ),
      { status: 401 },
    );
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };
}

async function requireOK(res: Response): Promise<void> {
  if (res.ok) return;
  if (res.status === 401)
    throw Object.assign(
      new Error("Your session is missing or expired. Sign in again."),
      { status: 401 },
    );
  if (res.status === 404)
    throw Object.assign(
      new Error("This analysis is unavailable to your account."),
      { status: 404 },
    );
  const data = (await res.json().catch(() => ({}))) as {
    detail?: string | { message?: string };
  };
  const message =
    typeof data.detail === "string" ? data.detail : data.detail?.message;
  throw Object.assign(new Error(message ?? `Request failed (${res.status}).`), {
    status: res.status,
    code: res.status === 402 ? "limit_reached" : undefined,
  });
}

export interface JobCreatedResponse {
  job_id: string;
  status: string;
}

export interface JobStatusResponse {
  job_id: string;
  status: "queued" | "running" | "finalizing" | "interrupted"
    | "processing" | "completed" | "insufficient_evidence" | "failed";
  current_step: string | null;
  error_message: string | null;
}

export async function createJob(
  inventionIdea: string,
  jurisdiction: string,
  submissionKey: string,
  jwt?: string,
  signal?: AbortSignal,
): Promise<JobCreatedResponse> {
  const headers = await authHeaders(jwt, signal);
  const res = await fetch(`${API_BASE}/jobs`, {
    signal,
    method: "POST",
    headers,
    body: JSON.stringify({
      invention_idea: inventionIdea, jurisdiction, submission_key: submissionKey,
    }),
  });

  await requireOK(res);

  return res.json() as Promise<JobCreatedResponse>;
}

export async function createCheckoutSession(
  jwt: string,
): Promise<{ checkout_url: string }> {
  const res = await fetch(`${API_BASE}/stripe/create-checkout-session`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${jwt}`,
    },
  });
  await requireOK(res);
  return res.json() as Promise<{ checkout_url: string }>;
}

export async function getJobStatus(
  jobId: string,
  signal?: AbortSignal,
): Promise<JobStatusResponse> {
  if (jobId === DEMO_JOB_ID)
    return {
      job_id: DEMO_JOB_ID,
      status: "completed",
      current_step: "done",
      error_message: null,
    };
  const res = await fetch(`${API_BASE}/jobs/${jobId}`, {
    signal,
    headers: await authHeaders(undefined, signal),
    cache: "no-store",
  });
  await requireOK(res);

  return res.json() as Promise<JobStatusResponse>;
}

export interface WhiteSpaceIdea {
  invention_name: string;
  one_liner: string;
  mechanism: string;
  key_differentiators: string[];
  why_novel: string;
}

export async function ideateWhiteSpace(
  searchId: string,
  title: string,
  description: string,
  signal?: AbortSignal,
): Promise<WhiteSpaceIdea> {
  if (searchId === DEMO_JOB_ID) return structuredClone(DEMO_IDEA);
  const res = await fetch(`${API_BASE}/jobs/${searchId}/ideate`, {
    signal,
    method: "POST",
    headers: await authHeaders(undefined, signal),
    body: JSON.stringify({
      white_space_title: title,
      white_space_description: description,
    }),
  });
  await requireOK(res);
  return res.json() as Promise<WhiteSpaceIdea>;
}

export interface ClaimResult {
  patent_id: string;
  title: string;
  likely_claims: string[];
  overlap_level: "high" | "medium" | "low" | "none";
  overlap_explanation: string;
  differentiators: string;
}

export async function analyzeClaimsRequest(
  searchId: string,
  signal?: AbortSignal,
): Promise<{ claims: ClaimResult[]; warnings?: string[] }> {
  if (searchId === DEMO_JOB_ID) return { claims: structuredClone(DEMO_CLAIMS) };
  const res = await fetch(`${API_BASE}/jobs/${searchId}/analyze-claims`, {
    signal,
    method: "POST",
    headers: await authHeaders(undefined, signal),
  });
  await requireOK(res);
  return res.json() as Promise<{ claims: ClaimResult[]; warnings?: string[] }>;
}

export async function getClaimsAnalysis(
  searchId: string,
  signal?: AbortSignal,
): Promise<{ claims: ClaimResult[] | null; warnings?: string[] }> {
  if (searchId === DEMO_JOB_ID) return { claims: structuredClone(DEMO_CLAIMS) };
  const res = await fetch(`${API_BASE}/jobs/${searchId}/analyze-claims`, {
    headers: await authHeaders(undefined, signal),
    cache: "no-store",
    signal,
  });
  await requireOK(res);
  return res.json() as Promise<{ claims: ClaimResult[] | null; warnings?: string[] }>;
}

export interface UsageStatus {
  plan: "free" | "pro";
  window_seconds: number;
  as_of: string;
  usage: Record<
    "job" | "claims" | "ideation",
    { used: number; limit: number; remaining: number }
  >;
}

export async function getUsageStatus(): Promise<UsageStatus> {
  const res = await fetch(`${API_BASE}/stripe/subscription-status`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  await requireOK(res);
  return res.json() as Promise<UsageStatus>;
}

export interface EvidenceObservation {
  provider: string;
  provider_record_id: string;
  publication_id: string | null;
  source_url: string | null;
  retrieved_at: string | null;
  matching_queries: string[];
  text: string;
  text_type: "abstract" | "search_snippet" | "title_only" | "synthetic";
  language: string | null;
  dates: { priority: string | null; filing: string | null; publication: string | null };
  requested_jurisdiction: string;
  jurisdiction_filter: { country: string } | null;
  coverage_limitations: string[];
}
export interface EvidencePatent {
  patent_id: string;
  title: string;
  abstract?: string | null;
  url?: string | null;
  evidence_status: "available" | "legacy_unknown" | "unsupported_version";
  evidence: { version: number; observations: EvidenceObservation[] } | null;
}
export interface EvidenceResponse {
  patents: EvidencePatent[];
  evidence_version: number | null;
  requested_jurisdiction: string | null;
  warnings: string[];
  clusters: { theme_name: string; description: string; patent_ids: string[]; ipc_codes?: string[]; top_assignees?: { name: string; count: number }[] }[];
  citation_links: { source: string; target: string; strength: number }[];
}
export async function getEvidence(jobId: string, signal?: AbortSignal): Promise<EvidenceResponse> {
  if (jobId === DEMO_JOB_ID) return structuredClone(DEMO_EVIDENCE);
  const res = await fetch(`${API_BASE}/jobs/${jobId}/evidence`, {
    headers: await authHeaders(undefined, signal), signal, cache: "no-store",
  });
  await requireOK(res);
  const data = await res.json() as EvidenceResponse;
  if (!Array.isArray(data.patents) || !Array.isArray(data.warnings) || !Array.isArray(data.clusters) || !Array.isArray(data.citation_links)) {
    throw new Error("Saved evidence response is unavailable. Retry reads saved data only.");
  }
  return data;
}
