"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createJob } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

const JOBS_KEY = "patentmapper_job_ids";
const MAX_CHARS = 2000;
const MIN_CHARS = 20;

function saveJobId(jobId: string): void {
  try {
    const existing = JSON.parse(
      localStorage.getItem(JOBS_KEY) ?? "[]"
    ) as string[];
    const updated = [jobId, ...existing.filter((id) => id !== jobId)].slice(
      0,
      20
    );
    localStorage.setItem(JOBS_KEY, JSON.stringify(updated));
  } catch {
    // localStorage may be unavailable in some contexts
  }
}

export default function Home() {
  const router = useRouter();
  const { session } = useAuth();
  const [inventionText, setInventionText] = useState("");
  const [jurisdiction, setJurisdiction] = useState("all");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showLimitModal, setShowLimitModal] = useState(false);

  const charCount = inventionText.length;
  const isTooShort = charCount > 0 && charCount < MIN_CHARS;
  const canSubmit = charCount >= MIN_CHARS && !isLoading;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;

    setIsLoading(true);
    setError(null);

    try {
      const { job_id } = await createJob(inventionText, jurisdiction, session?.access_token);
      saveJobId(job_id);
      router.push(`/results/${job_id}`);
    } catch (err) {
      if (
        err instanceof Error &&
        (err as Error & { code?: string }).code === "limit_reached"
      ) {
        setShowLimitModal(true);
        setIsLoading(false);
        return;
      }
      setError(
        err instanceof Error
          ? err.message
          : "Failed to connect to backend. Make sure it's running on port 8000."
      );
      setIsLoading(false);
    }
  }

  return (
    <main className="min-h-[calc(100vh-65px)] flex flex-col items-center justify-center px-4 py-16">
      <div className="w-full max-w-3xl">
        {/* Hero */}
        <div className="text-center mb-12">
          <h1 className="text-5xl font-bold tracking-tight mb-4">
            <span className="bg-gradient-to-r from-blue-400 to-purple-400 bg-clip-text text-transparent">
              Patent
            </span>
            <span className="text-white">Mapper</span>
          </h1>
          <p className="text-gray-400 text-lg max-w-xl mx-auto leading-relaxed">
            Describe your invention. We&apos;ll map the prior art landscape,
            surface white space, and generate a competitive brief — in seconds.
          </p>
        </div>

        {/* Form card */}
        <form
          onSubmit={handleSubmit}
          className="bg-gray-900 border border-gray-700 rounded-2xl p-8 shadow-2xl"
        >
          {/* Jurisdiction selector */}
          <div className="mb-6">
            <label className="block text-sm font-medium text-gray-300 mb-3">
              Jurisdiction
            </label>
            <div className="flex gap-2 flex-wrap">
              {(
                [
                  { value: "all", label: "All" },
                  { value: "us", label: "US" },
                  { value: "ep", label: "Europe" },
                  { value: "wo", label: "International" },
                ] as const
              ).map(({ value, label }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setJurisdiction(value)}
                  className={`px-4 py-1.5 rounded-lg border text-sm font-medium transition-colors ${
                    jurisdiction === value
                      ? "bg-blue-600 text-white border-blue-500"
                      : "bg-gray-800 text-gray-400 border-gray-700 hover:border-gray-500"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <label
            htmlFor="invention"
            className="block text-sm font-medium text-gray-300 mb-3"
          >
            Describe your invention
          </label>

          <div className="relative">
            <textarea
              id="invention"
              value={inventionText}
              onChange={(e) => setInventionText(e.target.value)}
              maxLength={MAX_CHARS}
              rows={7}
              placeholder="Describe your invention idea in plain english..."
              className="w-full bg-gray-800 border border-gray-600 rounded-xl px-4 py-3 text-gray-100 placeholder-gray-500 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all text-sm leading-relaxed"
              disabled={isLoading}
            />
            <span
              className={`absolute bottom-3 right-3 text-xs ${
                charCount > MAX_CHARS * 0.9
                  ? "text-yellow-500"
                  : "text-gray-500"
              }`}
            >
              {charCount}/{MAX_CHARS}
            </span>
          </div>

          {isTooShort && (
            <p className="text-yellow-500 text-xs mt-2">
              Please provide at least {MIN_CHARS} characters for a meaningful
              analysis.
            </p>
          )}

          {error && (
            <div className="mt-3 bg-red-950 border border-red-800 rounded-lg px-4 py-3">
              <p className="text-red-400 text-sm">{error}</p>
            </div>
          )}

          <button
            type="submit"
            disabled={!canSubmit}
            className="mt-5 w-full bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:cursor-not-allowed text-white font-semibold py-3 px-6 rounded-xl transition-colors flex items-center justify-center gap-2"
          >
            {isLoading ? (
              <>
                <svg
                  className="animate-spin h-4 w-4 text-white"
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  />
                </svg>
                Submitting...
              </>
            ) : (
              "Analyze Patents →"
            )}
          </button>
        </form>

        <p className="text-center text-gray-600 text-xs mt-5">
          No account needed. Results are saved in your browser.
        </p>
        <div className="text-center mt-3">
          <Link
            href="/dashboard"
            className="text-gray-500 hover:text-gray-400 text-xs transition-colors"
          >
            View past searches →
          </Link>
        </div>
      </div>

      {showLimitModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 px-4">
          <div className="bg-gray-900 border border-gray-700 rounded-2xl p-8 shadow-2xl w-full max-w-md">
            <h2 className="text-xl font-bold text-white mb-3">
              Monthly limit reached
            </h2>
            <p className="text-gray-400 text-sm mb-6">
              You&apos;ve used your 3 free analyses this month. Upgrade to Pro
              for unlimited searches.
            </p>
            <div className="flex flex-col gap-3">
              <Link
                href="/pricing"
                className="w-full text-center bg-blue-600 hover:bg-blue-500 text-white font-semibold py-3 px-6 rounded-xl transition-colors text-sm"
              >
                Upgrade to Pro →
              </Link>
              <button
                onClick={() => setShowLimitModal(false)}
                className="w-full text-center bg-gray-800 hover:bg-gray-700 text-gray-400 font-medium py-3 px-6 rounded-xl transition-colors text-sm"
              >
                Dismiss
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
