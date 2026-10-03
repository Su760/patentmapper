import { createClient } from "@/lib/supabase";
import { DEMO_JOB_ID, DEMO_IDEA, DEMO_CLAIMS } from "@/lib/demo";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

async function authHeaders(jwt?: string): Promise<Record<string, string>> {
  const { data, error } = await createClient().auth.getSession();
  const token = jwt ?? data.session?.access_token;
  if (error || !token)
    throw new Error(
      "Sign in to access private analyses, or view the synthetic demo.",
    );
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };
}

async function requireOK(res: Response): Promise<void> {
  if (res.ok) return;
  if (res.status === 401)
    throw new Error("Your session is missing or expired. Sign in again.");
  if (res.status === 404)
    throw new Error("This analysis is unavailable to your account.");
  const data = (await res.json().catch(() => ({}))) as {
    detail?: string | { message?: string };
  };
  const message =
    typeof data.detail === "string" ? data.detail : data.detail?.message;
  throw Object.assign(new Error(message ?? `Request failed (${res.status}).`), {
    code: res.status === 402 ? "limit_reached" : undefined,
  });
}

export interface JobCreatedResponse {
  job_id: string;
  status: string;
}

export interface JobStatusResponse {
  job_id: string;
  status: "processing" | "completed" | "failed";
  current_step: string | null;
  error_message: string | null;
}

export async function createJob(
  inventionIdea: string,
  jurisdiction: string,
  jwt?: string,
): Promise<JobCreatedResponse> {
  const headers = await authHeaders(jwt);
  const res = await fetch(`${API_BASE}/jobs`, {
    method: "POST",
    headers,
    body: JSON.stringify({ invention_idea: inventionIdea, jurisdiction }),
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
  if (!res.ok) {
    throw new Error(`Checkout session failed: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<{ checkout_url: string }>;
}

export async function getJobStatus(jobId: string): Promise<JobStatusResponse> {
  if (jobId === DEMO_JOB_ID)
    return {
      job_id: DEMO_JOB_ID,
      status: "completed",
      current_step: "done",
      error_message: null,
    };
  const res = await fetch(`${API_BASE}/jobs/${jobId}`, {
    headers: await authHeaders(),
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
): Promise<WhiteSpaceIdea> {
  if (searchId === DEMO_JOB_ID) return structuredClone(DEMO_IDEA);
  const res = await fetch(`${API_BASE}/jobs/${searchId}/ideate`, {
    method: "POST",
    headers: await authHeaders(),
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
): Promise<{ claims: ClaimResult[] }> {
  if (searchId === DEMO_JOB_ID) return { claims: structuredClone(DEMO_CLAIMS) };
  const res = await fetch(`${API_BASE}/jobs/${searchId}/analyze-claims`, {
    method: "POST",
    headers: await authHeaders(),
  });
  await requireOK(res);
  return res.json() as Promise<{ claims: ClaimResult[] }>;
}

export async function getClaimsAnalysis(
  searchId: string,
): Promise<{ claims: ClaimResult[] | null }> {
  if (searchId === DEMO_JOB_ID) return { claims: structuredClone(DEMO_CLAIMS) };
  const res = await fetch(`${API_BASE}/jobs/${searchId}/analyze-claims`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  await requireOK(res);
  return res.json() as Promise<{ claims: ClaimResult[] | null }>;
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
