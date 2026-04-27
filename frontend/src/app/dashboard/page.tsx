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
  created_at?: string | null;
}

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

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function StatusBadge({ status }: { status: DashboardItem["status"] }) {
  if (status === "completed") {
    return (
      <span className="pm-badge green">
        <span
          style={{
            width: 5,
            height: 5,
            borderRadius: 999,
            background: "currentColor",
            display: "inline-block",
          }}
        />
        Completed
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="pm-badge red">
        <span
          style={{
            width: 5,
            height: 5,
            borderRadius: 999,
            background: "currentColor",
            display: "inline-block",
          }}
        />
        Failed
      </span>
    );
  }
  return (
    <span className="pm-badge blue">
      <span
        style={{
          width: 5,
          height: 5,
          borderRadius: 999,
          background: "currentColor",
          display: "inline-block",
          animation: "pm-pulse 1.4s ease-in-out infinite",
        }}
      />
      Running
    </span>
  );
}

function DashboardContent() {
  const searchParams = useSearchParams();
  const { user, loading: authLoading } = useAuth();
  const [items, setItems] = useState<DashboardItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [showBanner, setShowBanner] = useState(false);
  const [filter, setFilter] = useState<
    "all" | "completed" | "processing" | "failed"
  >("all");
  const [q, setQ] = useState("");

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
      client
        .from("searches")
        .select(
          "id, invention_idea, status, current_step, error_message, created_at",
        )
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
              created_at: (row.created_at as string | null) ?? null,
            })),
          );
          setLoading(false);
        });
    } else {
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
              return (
                (data as { invention_idea: string } | null)?.invention_idea ??
                null
              );
            } catch {
              return null;
            }
          }),
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
              created_at: null,
            };
          }),
        );
        setLoading(false);
      });
    }
  }, [user, authLoading]);

  const filtered = items.filter(
    (item) =>
      (filter === "all" || item.status === filter) &&
      (q === "" ||
        (item.inventionIdea ?? "").toLowerCase().includes(q.toLowerCase())),
  );

  const filterTabs: {
    v: "all" | "completed" | "processing" | "failed";
    n: string;
  }[] = [
    { v: "all", n: "All" },
    { v: "completed", n: "Completed" },
    { v: "processing", n: "Running" },
    { v: "failed", n: "Failed" },
  ];

  return (
    <div className="pm" style={{ minHeight: "100%" }}>
      {showBanner && (
        <div
          style={{
            maxWidth: 1200,
            margin: "0 auto",
            padding: "16px 32px 0",
          }}
        >
          <div
            style={{
              background: "rgba(34,197,94,0.1)",
              border: "1px solid rgba(34,197,94,0.25)",
              borderRadius: 10,
              padding: "12px 16px",
              color: "#4ade80",
              fontSize: 13,
              fontWeight: 500,
            }}
          >
            Welcome to Pro! Unlimited analyses activated.
          </div>
        </div>
      )}

      <div className="pm-dash-head">
        <div>
          <h1 className="pm-dash-h1">Your analyses</h1>
          <div className="pm-dash-sub">
            {user
              ? "All past patent analyses from your account."
              : "All past patent analyses from this browser."}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Link href="/" className="pm-btn primary">
            + New analysis
          </Link>
        </div>
      </div>

      <div className="pm-dash-stats">
        <div className="pm-dash-stat">
          <div className="label">Total searches</div>
          <div className="value">
            {loading || authLoading ? (
              "—"
            ) : (
              <>
                {items.length}
                <span className="delta">this session</span>
              </>
            )}
          </div>
        </div>
        <div className="pm-dash-stat">
          <div className="label">Patents indexed</div>
          <div className="value">—</div>
        </div>
        <div className="pm-dash-stat">
          <div className="label">Avg. runtime</div>
          <div className="value">—</div>
        </div>
        <div className="pm-dash-stat">
          <div className="label">Plan</div>
          <div className="value" style={{ fontSize: 18 }}>
            {user ? "Pro" : "Free"}
            {user && (
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 11,
                  color: "var(--text-3)",
                }}
              >
                {" "}
                · $49/mo
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="pm-dash-toolbar">
        <div className="pm-search-input">
          <span
            style={{ fontFamily: "var(--font-mono)", color: "var(--text-3)" }}
          >
            ⌕
          </span>
          <input
            placeholder="Filter analyses by invention text…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <span
            className="mono"
            style={{
              fontSize: 10,
              padding: "2px 5px",
              border: "1px solid var(--border)",
              borderRadius: 4,
              color: "var(--text-3)",
            }}
          >
            /
          </span>
        </div>
        <div
          style={{
            display: "flex",
            gap: 4,
            padding: 3,
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 8,
          }}
        >
          {filterTabs.map((tab) => {
            const count =
              tab.v === "all"
                ? items.length
                : items.filter((r) => r.status === tab.v).length;
            return (
              <button
                key={tab.v}
                onClick={() => setFilter(tab.v)}
                className={`pm-jur${filter === tab.v ? " active" : ""}`}
                style={{ height: 28, fontSize: 12 }}
              >
                {tab.n}
                <span
                  style={{
                    fontFamily: "var(--font-mono)",
                    color: "var(--text-3)",
                    marginLeft: 6,
                    fontSize: 10,
                  }}
                >
                  {count}
                </span>
              </button>
            );
          })}
        </div>
        <button className="pm-btn sm">
          Sort: Newest <span style={{ fontFamily: "var(--font-mono)" }}>↓</span>
        </button>
      </div>

      <div className="pm-table-wrap">
        {(loading || authLoading) && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              color: "var(--text-3)",
              fontSize: 13,
              padding: "40px 0",
            }}
          >
            <div
              style={{
                width: 14,
                height: 14,
                border: "2px solid var(--border)",
                borderTopColor: "var(--text-2)",
                borderRadius: "50%",
                animation: "spin 0.8s linear infinite",
              }}
            />
            Loading searches…
          </div>
        )}

        {!loading && !authLoading && items.length === 0 && (
          <div
            style={{
              textAlign: "center",
              padding: "80px 0",
              color: "var(--text-3)",
            }}
          >
            <p style={{ fontSize: 16, marginBottom: 8 }}>No searches yet.</p>
            <p style={{ fontSize: 13, marginBottom: 20 }}>
              Analyses you run will appear here.
            </p>
            {!user && (
              <p style={{ fontSize: 13, marginBottom: 16 }}>
                <Link
                  href="/auth"
                  style={{ color: "var(--blue)", textDecoration: "none" }}
                >
                  Sign in
                </Link>{" "}
                to see your search history across devices.
              </p>
            )}
            <Link
              href="/"
              style={{
                color: "var(--blue)",
                fontSize: 13,
                textDecoration: "underline",
              }}
            >
              Start your first analysis →
            </Link>
          </div>
        )}

        {!loading && !authLoading && items.length > 0 && (
          <>
            <div className="pm-table">
              <div className="pm-table-head">
                <div>Invention</div>
                <div>Date</div>
                <div>Status</div>
                <div>Clusters</div>
                <div>Patents</div>
                <div />
              </div>
              {filtered.map((item, i) => {
                const stepLabel = item.current_step
                  ? (STEP_LABELS[item.current_step] ?? item.current_step)
                  : null;
                const fav = (item.inventionIdea ?? item.id)
                  .slice(0, 2)
                  .toUpperCase();

                return (
                  <Link
                    key={item.id}
                    href={`/results/${item.id}`}
                    className="pm-row"
                    style={{ textDecoration: "none" }}
                  >
                    <div className="pm-row-title">
                      <div
                        className="pm-row-fav"
                        style={{
                          background: `linear-gradient(135deg, hsl(${i * 47}, 50%, 28%), hsl(${i * 47 + 30}, 50%, 18%))`,
                          color: "white",
                        }}
                      >
                        {fav}
                      </div>
                      <div className="pm-row-title-text">
                        <h3>
                          {item.inventionIdea
                            ? item.inventionIdea.length > 80
                              ? item.inventionIdea.slice(0, 80) + "…"
                              : item.inventionIdea
                            : `Job ${item.id.slice(0, 8)}…`}
                        </h3>
                        <div className="pm-row-title-meta">
                          <span
                            className="mono"
                            style={{ fontSize: 10.5 }}
                          >{`id: ${item.id.slice(0, 8)}`}</span>
                          {stepLabel && item.status === "processing" && (
                            <span style={{ color: "var(--blue)" }}>
                              · {stepLabel}
                            </span>
                          )}
                          {item.error_message && item.status === "failed" && (
                            <span style={{ color: "var(--red)" }}>
                              · {item.error_message}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                    <div className="pm-row-mono">
                      {formatDate(item.created_at)}
                    </div>
                    <div>
                      <StatusBadge status={item.status} />
                    </div>
                    <div className="pm-row-mono">—</div>
                    <div className="pm-row-mono">—</div>
                    <div className="pm-row-arrow">→</div>
                  </Link>
                );
              })}
            </div>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "16px 4px",
                color: "var(--text-3)",
                fontSize: 12,
              }}
            >
              <span>
                Showing {filtered.length} of {items.length}
              </span>
              <div style={{ display: "flex", gap: 6 }}>
                <button className="pm-btn sm">←</button>
                <button className="pm-btn sm">→</button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <Suspense>
      <DashboardContent />
    </Suspense>
  );
}
