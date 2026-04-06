const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

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
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (jwt) headers["Authorization"] = `Bearer ${jwt}`;
  const res = await fetch(`${API_BASE}/jobs`, {
    method: "POST",
    headers,
    body: JSON.stringify({ invention_idea: inventionIdea, jurisdiction }),
  });

  if (res.status === 402) {
    const data = (await res.json()) as { detail: { message: string } };
    const message = data.detail?.message ?? "Monthly limit reached.";
    throw Object.assign(new Error(message), { code: "limit_reached" });
  }
  if (!res.ok) {
    throw new Error(`Failed to create job: ${res.status} ${res.statusText}`);
  }

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
  const res = await fetch(`${API_BASE}/jobs/${jobId}`);

  if (!res.ok) {
    throw new Error(
      `Failed to fetch job status: ${res.status} ${res.statusText}`,
    );
  }

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
  const res = await fetch(`${API_BASE}/jobs/${searchId}/ideate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      white_space_title: title,
      white_space_description: description,
    }),
  });
  if (!res.ok) throw new Error(`Ideate failed: ${res.status}`);
  return res.json() as Promise<WhiteSpaceIdea>;
}
