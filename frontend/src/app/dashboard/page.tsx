"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { getJobStatus } from "@/lib/api";
import { createClient } from "@/lib/supabase";
import { useAuth } from "@/lib/auth-context";

const JOBS_KEY = "patentmapper_job_ids";

interface DashboardItem {
  id: string;
  status: "processing" | "completed" | "failed" | null;
  current_step: string | null;
  error_message: string | null;
  inventionIdea: string | null;
}

const STATUS_STYLES: Record<string, string> = {
  processing: "bg-yellow-900 text-yellow-300 border-yellow-700",
  completed: "bg-green-900 text-green-300 border-green-700",
  failed: "bg-red-900 text-red-300 border-red-700",
};

const STEP_LABELS: Record<string, string> = {
  queued: "Getting ready...",
  generating_queries: "Generating search queries...",
  fetching_patents: "Fetching patents...",
  deduplicating: "Removing duplicates...",
  clustering: "Clustering by theme...",
  analyzing_gaps: "Analyzing white space...",
  writing_report: "Writing brief...",
  done: "Complete",
};

function DashboardContent() {
  const searchParams = useSearchParams();
  const { user, loading: authLoading } = useAuth();
  const [items, setItems] = useState<DashboardItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [showBanner, setShowBanner] = useState(false);

  useEffect(() => {
    if (searchParams.get("upgraded") === "true") {
      setShowBanner(true);
      const t = setTimeout(() => setShowBanner(false), 5000);
      return () => clearTimeout(t);
    }
  }, [searchParams]);

  useEffect(() => {
    if (authLoading) return;

    const client = createClient();

    if (user) {
      // Logged in: query Supabase directly by user_id
      client
        .from("searches")
        .select("id, invention_idea, status, current_step, error_message")
        .eq("user_id", user.id)
        .order("created_at", { ascending: false })
        .limit(20)
        .then(({ data }) => {
          setItems(
            (data ?? []).map((row) => ({
              id: row.id as string,
              status: row.status as DashboardItem["status"],
              current_step: (row.current_step as string | null) ?? null,
              error_message: (row.error_message as string | null) ?? null,
              inventionIdea: (row.invention_idea as string | null) ?? null,
            }))
          );
          setLoading(false);
        });
    } else {
      // Anonymous: use localStorage ids + API polling
      let ids: string[] = [];
      try {
        ids = JSON.parse(localStorage.getItem(JOBS_KEY) ?? "[]") as string[];
      } catch {
        ids = [];
      }

      if (ids.length === 0) {
        setLoading(false);
        return;
      }

      Promise.all([
        Promise.all(ids.map((id) => getJobStatus(id).catch(() => null))),
        Promise.all(
          ids.map(async (id) => {
            try {
              const { data } = await client
                .from("searches")
                .select("invention_idea")
                .eq("id", id)
                .single();
              return (data as { invention_idea: string } | null)?.invention_idea ?? null;
            } catch {
              return null;
            }
          })
        ),
      ]).then(([statuses, ideas]) => {
        setItems(
          ids.map((id, idx) => {
            const s = statuses[idx];
            return {
              id,
              status: s?.status ?? null,
              current_step: s?.current_step ?? null,
              error_message: s?.error_message ?? null,
              inventionIdea: ideas[idx],
            };
          })
        );
        setLoading(false);
      });
    }
  }, [user, authLoading]);

  return (
    <main className="min-h-[calc(100vh-65px)] px-4 py-10 max-w-3xl mx-auto">
      {showBanner && (
        <div className="mb-6 bg-green-900 border border-green-700 rounded-xl px-5 py-3 flex items-center gap-3">
          <span className="text-green-300 text-sm font-medium">
            Welcome to Pro! Unlimited analyses activated.
          </span>
        </div>
      )}

      <div className="flex items-start justify-between gap-4 mb-8">
        <div>
          <h1 className="text-2xl font-bold text-white mb-1">Your Searches</h1>
          <p className="text-gray-500 text-sm">
            {user
              ? "All past patent analyses from your account."
              : "All past patent analyses from this browser."}
          </p>
        </div>
        <Link
          href="/"
          className="bg-blue-600 hover:bg-blue-500 text-white text-sm font-semibold px-4 py-2 rounded-xl transition-colors shrink-0"
        >
          + New Analysis
        </Link>
      </div>

      {(loading || authLoading) && (
        <div className="flex items-center gap-3 text-gray-500 text-sm py-8">
          <div className="w-4 h-4 border-2 border-gray-600 border-t-gray-400 rounded-full animate-spin" />
          Loading searches...
        </div>
      )}

      {!loading && !authLoading && items.length === 0 && (
        <div className="text-center py-20">
          <p className="text-gray-500 text-lg mb-2">No searches yet.</p>
          <p className="text-gray-600 text-sm mb-6">
            Analyses you run will appear here.
          </p>
          {!user && (
            <p className="text-gray-600 text-sm mb-4">
              <Link
                href="/auth"
                className="text-blue-400 hover:text-blue-300 transition-colors"
              >
                Sign in
              </Link>{" "}
              to see your search history across devices.
            </p>
          )}
          <Link
            href="/"
            className="text-blue-400 hover:text-blue-300 text-sm underline transition-colors"
          >
            Start your first analysis →
          </Link>
        </div>
      )}

      {!loading && !authLoading && items.length > 0 && (
        <div className="flex flex-col gap-3">
          {items.map((item) => {
            const statusKey = item.status ?? "processing";
            const badgeStyle =
              STATUS_STYLES[statusKey] ??
              "bg-gray-800 text-gray-400 border-gray-600";
            const stepLabel = item.current_step
              ? (STEP_LABELS[item.current_step] ?? item.current_step)
              : null;

            return (
              <Link
                key={item.id}
                href={`/results/${item.id}`}
                className="block bg-gray-900 border border-gray-700 rounded-xl p-4 hover:border-gray-500 transition-colors group"
              >
                <div className="flex items-center justify-between gap-4">
                  <div className="min-w-0">
                    <p className="text-gray-200 text-sm font-medium group-hover:text-white transition-colors truncate">
                      {item.inventionIdea
                        ? item.inventionIdea.length > 80
                          ? item.inventionIdea.slice(0, 80) + "…"
                          : item.inventionIdea
                        : `Job ${item.id.slice(0, 8)}…`}
                    </p>
                    {stepLabel && statusKey === "processing" && (
                      <p className="text-gray-500 text-xs mt-0.5 truncate">
                        {stepLabel}
                      </p>
                    )}
                    {item.error_message && statusKey === "failed" && (
                      <p className="text-red-500 text-xs mt-0.5 truncate">
                        {item.error_message}
                      </p>
                    )}
                  </div>
                  <span
                    className={`text-xs px-2.5 py-1 rounded border shrink-0 capitalize ${badgeStyle}`}
                  >
                    {statusKey}
                  </span>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </main>
  );
}

export default function DashboardPage() {
  return (
    <Suspense>
      <DashboardContent />
    </Suspense>
  );
}
