"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { createCheckoutSession } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

const FREE_FEATURES = [
  "3 patent landscape analyses per month",
  "Prior art clusters + white space analysis",
  "PDF export & print",
  "Results saved for 30 days",
];

const PRO_FEATURES = [
  "Unlimited analyses",
  "Everything in Free",
  "Priority processing",
  "Search history forever",
  "Early access to new features",
];

export default function PricingPage() {
  const router = useRouter();
  const { session, loading: authLoading } = useAuth();
  const [plan, setPlan] = useState<"free" | "pro" | null>(null);
  const [upgrading, setUpgrading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!session) {
      setPlan("free");
      return;
    }
    fetch(`${API_BASE}/stripe/subscription-status`, {
      headers: { Authorization: `Bearer ${session.access_token}` },
    })
      .then((r) => r.json())
      .then((data: { plan: string }) =>
        setPlan(data.plan === "pro" ? "pro" : "free"),
      )
      .catch(() => setPlan("free"));
  }, [session]);

  async function handleUpgrade() {
    if (!session) {
      router.push("/auth?next=/pricing");
      return;
    }
    setUpgrading(true);
    setError(null);
    try {
      const { checkout_url } = await createCheckoutSession(
        session.access_token,
      );
      router.push(checkout_url);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to start checkout. Please try again.",
      );
      setUpgrading(false);
    }
  }

  const isLoaded = !authLoading && plan !== null;

  return (
    <div className="pm" style={{ minHeight: "100vh" }}>
      {/* Header */}
      <div style={{ textAlign: "center", paddingTop: 80 }}>
        <h1
          style={{
            fontSize: 36,
            fontWeight: 600,
            letterSpacing: "-0.03em",
            color: "var(--text)",
            margin: "0 0 12px",
          }}
        >
          Simple pricing
        </h1>
        <p style={{ color: "var(--text-2)", fontSize: 16, margin: 0 }}>
          Start free. Upgrade when you need more.
        </p>
      </div>

      {/* Cards grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 16,
          maxWidth: 800,
          margin: "48px auto 0",
          padding: "0 32px",
        }}
      >
        {/* Free card */}
        <div className="pm-cluster" style={{ padding: 32 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 8,
            }}
          >
            <span className="pm-cluster-section-label">Free</span>
            {isLoaded && plan === "free" && (
              <span className="pm-badge zinc">Current plan</span>
            )}
          </div>
          <div style={{ marginBottom: 24 }}>
            <span
              style={{
                fontSize: 36,
                fontWeight: 500,
                letterSpacing: "-0.03em",
                color: "var(--text)",
              }}
            >
              $0
            </span>
            <span
              style={{ color: "var(--text-3)", fontSize: 14, marginLeft: 6 }}
            >
              / month
            </span>
          </div>
          <ul
            style={{
              listStyle: "none",
              padding: 0,
              margin: "0 0 32px",
              display: "flex",
              flexDirection: "column",
              gap: 10,
            }}
          >
            {FREE_FEATURES.map((f) => (
              <li
                key={f}
                style={{ display: "flex", alignItems: "flex-start", gap: 8 }}
              >
                <span
                  style={{
                    width: 7,
                    height: 7,
                    borderRadius: "50%",
                    background: "var(--green)",
                    flexShrink: 0,
                    marginTop: 5,
                  }}
                />
                <span className="pm-player-name" style={{ fontSize: 13 }}>
                  {f}
                </span>
              </li>
            ))}
          </ul>
          <a
            href="/"
            className="pm-btn"
            style={{
              display: "block",
              width: "100%",
              textAlign: "center",
              boxSizing: "border-box",
            }}
          >
            Get started free →
          </a>
        </div>

        {/* Pro card */}
        <div
          className="pm-cluster"
          style={{
            padding: 32,
            border: "1px solid rgba(59,130,246,0.4)",
            background:
              "linear-gradient(160deg, var(--surface) 0%, var(--surface-2) 100%)",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 8,
            }}
          >
            <span className="pm-cluster-section-label">Pro</span>
            {isLoaded && plan === "pro" ? (
              <span className="pm-badge blue">Current plan</span>
            ) : (
              <span className="pm-badge blue">Most popular</span>
            )}
          </div>
          <div style={{ marginBottom: 24 }}>
            <span
              style={{
                fontSize: 36,
                fontWeight: 500,
                letterSpacing: "-0.03em",
                color: "var(--blue)",
              }}
            >
              $49
            </span>
            <span
              style={{ color: "var(--text-3)", fontSize: 14, marginLeft: 6 }}
            >
              / month
            </span>
          </div>
          <ul
            style={{
              listStyle: "none",
              padding: 0,
              margin: "0 0 32px",
              display: "flex",
              flexDirection: "column",
              gap: 10,
            }}
          >
            {PRO_FEATURES.map((f) => (
              <li
                key={f}
                style={{ display: "flex", alignItems: "flex-start", gap: 8 }}
              >
                <span
                  style={{
                    width: 7,
                    height: 7,
                    borderRadius: "50%",
                    background: "var(--green)",
                    flexShrink: 0,
                    marginTop: 5,
                  }}
                />
                <span className="pm-player-name" style={{ fontSize: 13 }}>
                  {f}
                </span>
              </li>
            ))}
          </ul>

          {error && (
            <div
              style={{
                marginBottom: 16,
                background: "rgba(239,68,68,0.08)",
                border: "1px solid rgba(239,68,68,0.3)",
                borderRadius: 8,
                padding: "12px 16px",
              }}
            >
              <p style={{ color: "var(--red)", fontSize: 13, margin: 0 }}>
                {error}
              </p>
            </div>
          )}

          {isLoaded && plan === "pro" ? (
            <div
              className="pm-btn"
              style={{
                display: "block",
                width: "100%",
                textAlign: "center",
                boxSizing: "border-box",
                cursor: "default",
                opacity: 0.6,
              }}
            >
              You&apos;re on Pro
            </div>
          ) : (
            <button
              onClick={handleUpgrade}
              disabled={upgrading || !isLoaded}
              className="pm-btn primary"
              style={{
                width: "100%",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 8,
                boxSizing: "border-box",
              }}
            >
              {upgrading ? (
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
                  Redirecting to checkout...
                </>
              ) : (
                "Upgrade to Pro →"
              )}
            </button>
          )}
          <p
            className="pm-cluster-section-label"
            style={{ textAlign: "center", marginTop: 12 }}
          >
            14-day money-back guarantee
          </p>
        </div>
      </div>

      {/* Footer link */}
      <div style={{ textAlign: "center", marginTop: 40, paddingBottom: 80 }}>
        <span style={{ color: "var(--text-3)", fontSize: 13 }}>
          Questions?{" "}
        </span>
        <a href="/auth" className="pm-nav-link" style={{ fontSize: 13 }}>
          Contact us
        </a>
      </div>
    </div>
  );
}
