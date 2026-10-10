"use client";

import { UsageStatus } from "@/lib/api";

export default function UsageSummary({
  data,
  error,
  loading,
  signedIn,
  retry,
}: {
  data?: UsageStatus;
  error?: string;
  loading: boolean;
  signedIn: boolean;
  retry: () => void;
}) {
  if (loading) return <p role="status">Loading usage…</p>;
  if (!signedIn)
    return <p>Synthetic demo only. Sign in for private analyses.</p>;
  if (error)
    return (
      <p role="alert">
        {error}{" "}
        <button className="pm-btn sm" onClick={retry}>
          Retry usage
        </button>
      </p>
    );
  if (!data) return null;
  return (
    <div aria-label="Usage allowance">
      <p>
        {data.plan === "pro" ? "Pro" : "Free"} · rolling{" "}
        {data.window_seconds / 86400} days
      </p>
      <p>
        {(
          [
            ["job", "Analyses"],
            ["claims", "Claims"],
            ["ideation", "Ideas"],
          ] as const
        )
          .map(
            ([key, label]) =>
              `${label}: ${data.usage[key].used}/${data.usage[key].limit} used (${data.usage[key].remaining} remaining)`,
          )
          .join(" · ")}
      </p>
      <p>
        Accepted attempts consume usage, including failed attempts. Viewing
        saved results and the demo is free.
      </p>
      <button className="pm-btn sm" onClick={retry}>
        Refresh usage
      </button>
    </div>
  );
}
