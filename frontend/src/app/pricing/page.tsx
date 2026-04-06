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

function CheckIcon() {
  return (
    <svg
      className="w-4 h-4 text-green-400 shrink-0 mt-0.5"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2.5}
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  );
}

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
    <main className="min-h-[calc(100vh-65px)] flex flex-col items-center justify-center px-4 py-16">
      <div className="w-full max-w-4xl">
        {/* Header */}
        <div className="text-center mb-12">
          <h1 className="text-4xl font-bold text-white mb-3">Simple pricing</h1>
          <p className="text-gray-400 text-lg max-w-xl mx-auto">
            Start free. Upgrade when you need more.
          </p>
        </div>

        {/* Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-start">
          {/* Free card */}
          <div className="bg-gray-900 border border-gray-700 rounded-2xl p-8">
            <div className="flex items-center justify-between mb-1">
              <h2 className="text-xl font-bold text-white">Free</h2>
              {isLoaded && plan === "free" && (
                <span className="text-xs bg-gray-700 text-gray-300 px-2.5 py-1 rounded-full border border-gray-600">
                  Current plan
                </span>
              )}
            </div>
            <div className="mb-6">
              <span className="text-4xl font-bold text-white">$0</span>
              <span className="text-gray-500 ml-1">/ month</span>
            </div>
            <ul className="space-y-3 mb-8">
              {FREE_FEATURES.map((f) => (
                <li
                  key={f}
                  className="flex items-start gap-2 text-gray-300 text-sm"
                >
                  <CheckIcon />
                  {f}
                </li>
              ))}
            </ul>
            <a
              href="/"
              className="block w-full text-center bg-gray-800 hover:bg-gray-700 text-white font-semibold py-3 px-6 rounded-xl transition-colors text-sm"
            >
              Get started free →
            </a>
          </div>

          {/* Pro card */}
          <div className="bg-gray-900 border-2 border-blue-500 rounded-2xl p-8 shadow-xl shadow-blue-950/40">
            <div className="flex items-center justify-between mb-1">
              <h2 className="text-xl font-bold text-white">Pro</h2>
              {isLoaded && plan === "pro" ? (
                <span className="text-xs bg-blue-900 text-blue-300 px-2.5 py-1 rounded-full border border-blue-700">
                  Current plan
                </span>
              ) : (
                <span className="text-xs bg-blue-600 text-white px-2.5 py-1 rounded-full">
                  Most popular
                </span>
              )}
            </div>
            <div className="mb-6">
              <span className="text-4xl font-bold text-white">$49</span>
              <span className="text-gray-500 ml-1">/ month</span>
            </div>
            <ul className="space-y-3 mb-8">
              {PRO_FEATURES.map((f) => (
                <li
                  key={f}
                  className="flex items-start gap-2 text-gray-300 text-sm"
                >
                  <CheckIcon />
                  {f}
                </li>
              ))}
            </ul>

            {error && (
              <div className="mb-4 bg-red-950 border border-red-800 rounded-lg px-4 py-3">
                <p className="text-red-400 text-sm">{error}</p>
              </div>
            )}

            {isLoaded && plan === "pro" ? (
              <div className="w-full text-center bg-gray-800 text-gray-400 font-semibold py-3 px-6 rounded-xl text-sm cursor-default">
                You&apos;re on Pro
              </div>
            ) : (
              <button
                onClick={handleUpgrade}
                disabled={upgrading || !isLoaded}
                className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:cursor-not-allowed text-white font-semibold py-3 px-6 rounded-xl transition-colors flex items-center justify-center gap-2 text-sm"
              >
                {upgrading ? (
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
                    Redirecting to checkout...
                  </>
                ) : (
                  "Upgrade to Pro →"
                )}
              </button>
            )}
            <p className="text-center text-gray-600 text-xs mt-3">
              14-day money-back guarantee
            </p>
          </div>
        </div>
      </div>
    </main>
  );
}
