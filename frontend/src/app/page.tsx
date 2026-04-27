"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createJob } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

const JOBS_KEY = "patentmapper_job_ids";
const MAX_CHARS = 2000;
const MIN_CHARS = 20;

const JURISDICTIONS = [
  { value: "all", label: "All" },
  { value: "us", label: "US" },
  { value: "ep", label: "Europe" },
  { value: "wo", label: "International" },
] as const;

type JurisdictionValue = (typeof JURISDICTIONS)[number]["value"];

function saveJobId(jobId: string): void {
  try {
    const existing = JSON.parse(
      localStorage.getItem(JOBS_KEY) ?? "[]",
    ) as string[];
    const updated = [jobId, ...existing.filter((id) => id !== jobId)].slice(
      0,
      20,
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
  const [jurisdiction, setJurisdiction] = useState<JurisdictionValue>("all");
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
      const { job_id } = await createJob(
        inventionText,
        jurisdiction,
        session?.access_token,
      );
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
          : "Failed to connect to backend. Make sure it's running on port 8000.",
      );
      setIsLoading(false);
    }
  }

  const jurLabel =
    JURISDICTIONS.find((j) => j.value === jurisdiction)?.label ?? "All";

  return (
    <div className="pm" style={{ minHeight: "100%" }}>
      <section className="pm-hero">
        <div className="pm-hero-bg" />
        <div className="pm-hero-grid" />
        <div className="pm-hero-inner">
          <div className="pm-hero-eyebrow">
            <span className="pulse" />
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                letterSpacing: "0.04em",
              }}
            >
              AI-powered · USPTO · Lens.org · Google Patents
            </span>
          </div>

          <h1 className="pm-h1">
            Map your patent landscape
            <br />
            <span className="accent">in 60 seconds.</span>
          </h1>

          <p className="pm-hero-sub">
            Six AI agents fan out across USPTO, Lens, and Google Patents —
            returning clusters, white-space gaps, and a relationship graph. Skip
            the $500/mo enterprise tools.
          </p>

          <form onSubmit={handleSubmit} className="pm-form-shell">
            <div className="pm-form-inner">
              <div className="pm-form-row">
                <div className="pm-form-label">
                  <span
                    style={{
                      width: 6,
                      height: 6,
                      borderRadius: 999,
                      background: "var(--blue)",
                      boxShadow: "0 0 6px var(--blue)",
                    }}
                  />
                  Describe your invention
                </div>
                <div className="pm-jur-group">
                  {JURISDICTIONS.map(({ value, label }) => (
                    <button
                      key={value}
                      type="button"
                      className={`pm-jur${jurisdiction === value ? " active" : ""}`}
                      onClick={() => setJurisdiction(value)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              <textarea
                id="invention"
                className="pm-textarea"
                value={inventionText}
                onChange={(e) => setInventionText(e.target.value)}
                maxLength={MAX_CHARS}
                rows={7}
                placeholder="A microfluidic device that separates exosomes from whole blood using acoustic..."
                disabled={isLoading}
              />

              {isTooShort && (
                <p
                  style={{
                    color: "var(--yellow)",
                    fontSize: 12,
                    marginTop: 8,
                  }}
                >
                  Please provide at least {MIN_CHARS} characters for a
                  meaningful analysis.
                </p>
              )}

              {error && (
                <div
                  style={{
                    marginTop: 12,
                    background: "rgba(239,68,68,0.08)",
                    border: "1px solid rgba(239,68,68,0.3)",
                    borderRadius: 8,
                    padding: "10px 14px",
                  }}
                >
                  <p style={{ color: "var(--red)", fontSize: 13 }}>{error}</p>
                </div>
              )}

              <div className="pm-form-foot">
                <div className="pm-form-foot-left">
                  <span
                    className="mono"
                    style={{
                      color:
                        charCount > MAX_CHARS * 0.9
                          ? "var(--yellow)"
                          : "var(--text-3)",
                    }}
                  >
                    {charCount} / {MAX_CHARS}
                  </span>
                  <span style={{ color: "var(--border-strong)" }}>·</span>
                  <span>
                    Jurisdiction:{" "}
                    <span style={{ color: "var(--text-2)" }}>{jurLabel}</span>
                  </span>
                  <span style={{ color: "var(--border-strong)" }}>·</span>
                  <span>~58s avg</span>
                </div>
                <button
                  type="submit"
                  disabled={!canSubmit}
                  className="pm-btn primary lg"
                  style={
                    !canSubmit ? { opacity: 0.5, cursor: "not-allowed" } : {}
                  }
                >
                  {isLoading ? (
                    <>
                      <svg
                        style={{
                          animation: "spin 1s linear infinite",
                          width: 16,
                          height: 16,
                        }}
                        xmlns="http://www.w3.org/2000/svg"
                        fill="none"
                        viewBox="0 0 24 24"
                      >
                        <circle
                          style={{ opacity: 0.25 }}
                          cx="12"
                          cy="12"
                          r="10"
                          stroke="currentColor"
                          strokeWidth="4"
                        />
                        <path
                          style={{ opacity: 0.75 }}
                          fill="currentColor"
                          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                        />
                      </svg>
                      Submitting...
                    </>
                  ) : (
                    <>
                      Analyze patents
                      <span style={{ fontFamily: "var(--font-mono)" }}>→</span>
                    </>
                  )}
                </button>
              </div>
            </div>
          </form>

          <div className="pm-stats">
            <div className="pm-stat">
              <div className="pm-stat-num">
                70<span className="unit">+</span>
              </div>
              <div className="pm-stat-label">patents analyzed per search</div>
            </div>
            <div className="pm-stat">
              <div className="pm-stat-num">5</div>
              <div className="pm-stat-label">AI-powered semantic clusters</div>
            </div>
            <div className="pm-stat">
              <div className="pm-stat-num">3</div>
              <div className="pm-stat-label">
                white-space opportunities surfaced
              </div>
            </div>
          </div>

          <div className="pm-foot-note">
            No account needed · Results saved in your browser ·{" "}
            <Link
              href="/dashboard"
              style={{ color: "var(--text-3)", textDecoration: "none" }}
            >
              View past searches →
            </Link>
          </div>
        </div>
      </section>

      {showLimitModal && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.7)",
            backdropFilter: "blur(4px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 50,
            padding: "0 16px",
          }}
        >
          <div
            style={{
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: 16,
              padding: 32,
              width: "100%",
              maxWidth: 400,
            }}
          >
            <h2
              style={{
                fontSize: 20,
                fontWeight: 600,
                margin: "0 0 12px",
                letterSpacing: "-0.02em",
              }}
            >
              Monthly limit reached
            </h2>
            <p
              style={{
                color: "var(--text-2)",
                fontSize: 14,
                marginBottom: 24,
                lineHeight: 1.55,
              }}
            >
              You&apos;ve used your 3 free analyses this month. Upgrade to Pro
              for unlimited searches.
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <Link
                href="/pricing"
                className="pm-btn primary lg"
                style={{
                  width: "100%",
                  justifyContent: "center",
                  textDecoration: "none",
                }}
              >
                Upgrade to Pro →
              </Link>
              <button
                onClick={() => setShowLimitModal(false)}
                className="pm-btn lg"
                style={{ width: "100%" }}
              >
                Dismiss
              </button>
            </div>
          </div>
        </div>
      )}

      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
