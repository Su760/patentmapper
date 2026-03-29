"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import dynamic from "next/dynamic";
import { getJobStatus } from "@/lib/api";
import { createClient } from "@/lib/supabase";
import MarkdownRenderer from "@/components/MarkdownRenderer";
import "./print.css";

// ─── Dynamic import for graph (SSR disabled — canvas API) ────────────────────
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

// ─── Types ───────────────────────────────────────────────────────────────────

type Phase = "init" | "polling" | "loading_results" | "completed" | "failed";

interface Cluster {
  theme_name: string;
  description: string;
  patent_ids: string[];
  ipc_codes?: string[];
  top_assignees?: { name: string; count: number }[];
  filing_trend?: { year: number; count: number }[];
}

interface CitationLink {
  source: string;
  target: string;
  strength: number;
}

interface SearchResult {
  clusters: Cluster[];
  white_space_analysis: string;
  citation_links?: CitationLink[];
}

interface SearchMeta {
  invention_idea: string;
  created_at: string;
}

interface WhiteSpaceGap {
  title: string;
  viability: string;
  description: string;
}

interface GraphNode {
  id: string;
  clusterIdx: number;
  clusterName: string;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const STEPS = [
  { key: "queued", label: "Getting ready..." },
  { key: "generating_queries", label: "Generating search queries..." },
  { key: "fetching_patents", label: "Fetching patents from databases..." },
  { key: "deduplicating", label: "Removing duplicates..." },
  { key: "clustering", label: "Clustering by theme..." },
  { key: "analyzing_gaps", label: "Analyzing white space..." },
  { key: "writing_report", label: "Writing your brief..." },
  { key: "done", label: "Complete!" },
] as const;

const STEPPER_MIN_MS = 1500;
const SIMULATE_INTERVAL_MS = 2000;
const POLL_INTERVAL_MS = 3000;

const VIABILITY_STYLES: Record<string, string> = {
  High: "bg-green-900 text-green-300 border-green-700",
  Medium: "bg-yellow-900 text-yellow-300 border-yellow-700",
  Low: "bg-red-900 text-red-300 border-red-700",
};

const CLUSTER_COLORS = [
  "#60a5fa", // blue-400
  "#a78bfa", // violet-400
  "#34d399", // emerald-400
  "#fb923c", // orange-400
  "#f472b6", // pink-400
  "#facc15", // yellow-400
];

// ─── Helpers ──────────────────────────────────────────────────────────────────

function parseWhiteSpace(md: string): WhiteSpaceGap[] {
  return md
    .split(/(?=### Gap \d+:)/)
    .filter((s) => s.trim().startsWith("### Gap"))
    .map((section) => {
      const title =
        section.match(/### Gap \d+:\s*(.+)/)?.[1]?.trim() ?? "Unknown Gap";
      const viability =
        section.match(/\*\*Viability:\s*(.*?)\*\*/)?.[1]?.trim() ?? "Unknown";
      const description = section
        .replace(/### Gap \d+:.+\n/, "")
        .replace(/\*\*Viability:.*?\*\*\n?/, "")
        .trim();
      return { title, viability, description };
    });
}

function buildGraphData(clusters: Cluster[], citationLinks: CitationLink[]) {
  const nodeMap = new Map<string, GraphNode>();
  clusters.forEach((cluster, idx) => {
    cluster.patent_ids.forEach((pid) => {
      if (!nodeMap.has(pid)) {
        nodeMap.set(pid, { id: pid, clusterIdx: idx, clusterName: cluster.theme_name });
      }
    });
  });

  // Include any node referenced in links even if not in clusters
  citationLinks.forEach(({ source, target }) => {
    if (!nodeMap.has(source)) nodeMap.set(source, { id: source, clusterIdx: 0, clusterName: "" });
    if (!nodeMap.has(target)) nodeMap.set(target, { id: target, clusterIdx: 0, clusterName: "" });
  });

  return {
    nodes: Array.from(nodeMap.values()),
    links: citationLinks.map((l) => ({ source: l.source, target: l.target, strength: l.strength })),
  };
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function Stepper({ stepIdx }: { stepIdx: number }) {
  return (
    <div className="w-full max-w-lg mx-auto">
      {STEPS.map((step, idx) => {
        const isDone = idx < stepIdx;
        const isActive = idx === stepIdx;
        const isPending = idx > stepIdx;

        return (
          <div key={step.key} className="flex items-start gap-4 mb-4">
            {/* Circle indicator */}
            <div className="flex flex-col items-center">
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center border-2 shrink-0 ${
                  isDone
                    ? "bg-green-500 border-green-500"
                    : isActive
                    ? "border-blue-400 bg-transparent"
                    : "border-gray-700 bg-transparent"
                }`}
              >
                {isDone ? (
                  <svg
                    className="w-4 h-4 text-white"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={3}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M5 13l4 4L19 7"
                    />
                  </svg>
                ) : isActive ? (
                  <div className="w-3 h-3 bg-blue-400 rounded-full animate-pulse" />
                ) : (
                  <div className="w-2 h-2 bg-gray-700 rounded-full" />
                )}
              </div>
              {idx < STEPS.length - 1 && (
                <div
                  className={`w-0.5 h-4 mt-1 ${
                    isDone ? "bg-green-500" : "bg-gray-700"
                  }`}
                />
              )}
            </div>

            {/* Label */}
            <p
              className={`text-sm pt-1.5 ${
                isDone
                  ? "text-gray-500 line-through"
                  : isActive
                  ? "text-blue-300 font-medium"
                  : isPending
                  ? "text-gray-600"
                  : "text-gray-400"
              }`}
            >
              {step.label}
            </p>
          </div>
        );
      })}
    </div>
  );
}

function WhiteSpaceCard({ gap }: { gap: WhiteSpaceGap }) {
  const badgeStyle =
    VIABILITY_STYLES[gap.viability] ??
    "bg-gray-800 text-gray-300 border-gray-600";

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 flex flex-col gap-3 print:break-inside-avoid">
      <div className="flex items-start justify-between gap-4">
        <h3 className="text-white font-semibold text-base leading-snug">
          {gap.title}
        </h3>
        <span
          className={`text-xs px-2 py-1 rounded border shrink-0 ${badgeStyle}`}
        >
          {gap.viability}
        </span>
      </div>
      <p className="text-gray-400 text-sm leading-relaxed">{gap.description}</p>
    </div>
  );
}

function TrendCard({ cluster }: { cluster: Cluster }) {
  const trend = cluster.filing_trend ?? [];
  const W = 120, H = 50, barW = 4, gap = 2;
  const maxCount = Math.max(...trend.map((t) => t.count), 1);
  const latestYear = trend[trend.length - 1]?.year;
  const totalBarSpace = trend.length * (barW + gap) - gap;
  const startX = (W - totalBarSpace) / 2;

  const firstAvg = trend.length >= 2 ? (trend[0].count + trend[1].count) / 2 : 0;
  const lastAvg =
    trend.length >= 2
      ? (trend[trend.length - 2].count + trend[trend.length - 1].count) / 2
      : 0;
  const indicator =
    lastAvg > firstAvg * 1.2
      ? { label: "↑ Accelerating", cls: "text-green-400" }
      : lastAvg < firstAvg * 0.8
      ? { label: "↓ Slowing", cls: "text-gray-500" }
      : { label: "→ Stable", cls: "text-yellow-400" };

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-xl p-4 min-w-[180px] flex flex-col gap-2">
      <p className="text-white text-xs font-medium truncate">
        {cluster.theme_name.length > 30
          ? cluster.theme_name.slice(0, 30) + "…"
          : cluster.theme_name}
      </p>
      <svg width={W} height={H} className="overflow-visible">
        {trend.map((t, i) => {
          const barH = Math.max(2, Math.round((t.count / maxCount) * H));
          const x = startX + i * (barW + gap);
          return (
            <rect
              key={t.year}
              x={x}
              y={H - barH}
              width={barW}
              height={barH}
              fill={t.year === latestYear ? "#60a5fa" : "#3b82f6"}
              rx={1}
            />
          );
        })}
      </svg>
      <p className="text-xs text-gray-500">
        {trend[0].year} → {latestYear}
      </p>
      <p className={`text-xs font-medium ${indicator.cls}`}>{indicator.label}</p>
    </div>
  );
}

function ClusterCard({ cluster }: { cluster: Cluster }) {
  return (
    <div className="bg-gray-900 border border-gray-700 rounded-xl p-5 flex flex-col gap-3 print:break-inside-avoid">
      <div className="flex items-center gap-2">
        <span className="w-2 h-2 rounded-full bg-blue-400 shrink-0" />
        <h3 className="text-white font-semibold text-sm">{cluster.theme_name}</h3>
      </div>
      <p className="text-gray-400 text-xs leading-relaxed">{cluster.description}</p>
      {cluster.ipc_codes && cluster.ipc_codes.length > 0 && (
        <div className="flex flex-col gap-1">
          <span className="text-xs text-gray-500">Classifications</span>
          <div className="flex flex-wrap gap-1">
            {cluster.ipc_codes.slice(0, 2).map((code) => (
              <span
                key={code}
                className="text-xs font-mono text-gray-400 bg-gray-800 px-2 py-0.5 rounded border border-gray-700"
              >
                {code}
              </span>
            ))}
          </div>
        </div>
      )}
      {cluster.top_assignees && cluster.top_assignees.length > 0 && (
        <div className="flex flex-col gap-1">
          <span className="text-xs text-gray-500">Key players</span>
          <div className="flex flex-wrap gap-2">
            {cluster.top_assignees.slice(0, 3).map((a) => (
              <div key={a.name} className="flex items-center gap-1">
                <span className="text-xs text-gray-300">
                  {a.name.length > 24 ? a.name.slice(0, 24) + "…" : a.name}
                </span>
                <span className="text-xs text-gray-500 bg-gray-800 px-1.5 rounded">
                  ×{a.count}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="flex flex-wrap gap-1.5 mt-1">
        {cluster.patent_ids.map((pid) => (
          <a
            key={pid}
            href={`https://patents.google.com/patent/${pid}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs font-mono text-blue-400 hover:text-blue-300 bg-gray-800 px-2 py-1 rounded border border-gray-700 hover:border-blue-700 transition-colors"
          >
            {pid}
          </a>
        ))}
      </div>
    </div>
  );
}

function PatentGraphSection({
  clusters,
  citationLinks,
  onNodeClick,
}: {
  clusters: Cluster[];
  citationLinks: CitationLink[];
  onNodeClick: (node: GraphNode) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    setWidth(el.offsetWidth);
    const ro = new ResizeObserver(() => setWidth(el.offsetWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const graphData = buildGraphData(clusters, citationLinks);

  return (
    <div
      ref={containerRef}
      className="w-full h-[400px] rounded-xl overflow-hidden border border-gray-700 bg-gray-950"
    >
      <ForceGraph2D
        graphData={graphData}
        width={width}
        height={400}
        backgroundColor="transparent"
        nodeColor={(node) => {
          const n = node as GraphNode;
          return CLUSTER_COLORS[n.clusterIdx % CLUSTER_COLORS.length];
        }}
        nodeVal={4}
        nodeLabel="id"
        linkWidth={(link) => {
          const l = link as { strength: number };
          return l.strength * 2;
        }}
        linkColor={() => "rgba(100,116,139,0.4)"}
        d3VelocityDecay={0.3}
        cooldownTime={2000}
        onNodeClick={(node) => onNodeClick(node as GraphNode)}
      />
    </div>
  );
}

function NodeSidePanel({
  node,
  clusters,
  onClose,
}: {
  node: GraphNode;
  clusters: Cluster[];
  onClose: () => void;
}) {
  // Click-outside to close
  const panelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function handleMouseDown(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        onClose();
      }
    }
    document.addEventListener("mousedown", handleMouseDown);
    return () => document.removeEventListener("mousedown", handleMouseDown);
  }, [onClose]);

  // Find the cluster this patent belongs to
  const cluster = clusters.find((c) => c.patent_ids.includes(node.id));

  return (
    <div
      ref={panelRef}
      className="fixed right-4 top-1/4 w-72 bg-gray-900 border border-gray-700 rounded-xl p-5 shadow-2xl z-50"
    >
      <div className="flex items-start justify-between mb-4">
        <span className="text-xs text-gray-500 font-medium uppercase tracking-wide">Patent</span>
        <button
          onClick={onClose}
          className="text-gray-500 hover:text-gray-300 transition-colors text-lg leading-none"
          aria-label="Close"
        >
          ×
        </button>
      </div>
      <p className="font-mono text-white text-sm font-semibold mb-3 break-all">{node.id}</p>
      {cluster && (
        <div className="mb-4">
          <span className="text-xs text-gray-500">Cluster</span>
          <p className="text-gray-300 text-xs mt-1">{cluster.theme_name}</p>
        </div>
      )}
      <a
        href={`https://patents.google.com/patent/${node.id}`}
        target="_blank"
        rel="noopener noreferrer"
        className="block text-blue-400 hover:text-blue-300 text-xs font-medium transition-colors"
      >
        View on Google Patents →
      </a>
    </div>
  );
}

// ─── Main Client Component ────────────────────────────────────────────────────

export default function ResultsClient({ jobId }: { jobId: string }) {
  const [phase, setPhase] = useState<Phase>("init");
  const [currentStep, setCurrentStep] = useState<string | null>(null);
  const [simulatedStepIdx, setSimulatedStepIdx] = useState(0);
  const [inventionIdea, setInventionIdea] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [searchMeta, setSearchMeta] = useState<SearchMeta | null>(null);
  const [searchResult, setSearchResult] = useState<SearchResult | null>(null);
  const [copied, setCopied] = useState(false);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);

  const stepperStartedAt = useRef<number>(0);

  // Fetch invention_idea early so loading_results screen has context
  const fetchInventionIdea = useCallback(async () => {
    const client = createClient();
    const { data } = await client
      .from("searches")
      .select("invention_idea")
      .eq("id", jobId)
      .single();
    if (data?.invention_idea) setInventionIdea(data.invention_idea);
  }, [jobId]);

  const loadResults = useCallback(async () => {
    const client = createClient();
    const [searchRes, resultsRes] = await Promise.all([
      client
        .from("searches")
        .select("invention_idea, created_at")
        .eq("id", jobId)
        .single(),
      client
        .from("search_results")
        .select("clusters, white_space_analysis, citation_links")
        .eq("search_id", jobId)
        .single(),
    ]);

    if (searchRes.error || resultsRes.error) {
      setErrorMessage("Could not load results from database.");
      setPhase("failed");
      return;
    }

    setSearchMeta(searchRes.data as SearchMeta);
    setSearchResult(resultsRes.data as SearchResult);
    setPhase("completed");
  }, [jobId]);

  function handlePrint() {
    const prev = document.title;
    const idea = searchMeta?.invention_idea ?? "";
    document.title = `PatentMapper - ${idea.slice(0, 60)}`;
    window.print();
    document.title = prev;
  }

  async function handleCopyLink() {
    await navigator.clipboard.writeText(window.location.href);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  // ── Effect 1: Initial status check on mount ──
  useEffect(() => {
    getJobStatus(jobId)
      .then((status) => {
        if (status.status === "completed") {
          // Already done — skip stepper, go straight to loading_results
          setPhase("loading_results");
          fetchInventionIdea();
          loadResults();
        } else if (status.status === "failed") {
          setErrorMessage(status.error_message ?? "Analysis failed.");
          setPhase("failed");
        } else {
          // processing — show stepper, record start time
          setCurrentStep(status.current_step);
          stepperStartedAt.current = Date.now();
          setPhase("polling");
        }
      })
      .catch(console.warn);
  }, [jobId, fetchInventionIdea, loadResults]);

  // ── Effect 2: Simulated step animation while polling ──
  useEffect(() => {
    if (phase !== "polling") return;

    const id = setInterval(() => {
      setSimulatedStepIdx((prev) => Math.min(prev + 1, STEPS.length - 2));
    }, SIMULATE_INTERVAL_MS);

    return () => clearInterval(id);
  }, [phase]);

  // ── Effect 3: Real status polling while polling ──
  useEffect(() => {
    if (phase !== "polling") return;

    const intervalId = setInterval(async () => {
      try {
        const status = await getJobStatus(jobId);

        if (status.status === "completed") {
          clearInterval(intervalId);
          // Enforce minimum stepper display time
          const elapsed = Date.now() - stepperStartedAt.current;
          const delay = Math.max(0, STEPPER_MIN_MS - elapsed);
          setTimeout(() => {
            setPhase("loading_results");
            fetchInventionIdea();
            loadResults();
          }, delay);
        } else if (status.status === "failed") {
          clearInterval(intervalId);
          setErrorMessage(status.error_message ?? "Analysis failed.");
          setPhase("failed");
        } else {
          setCurrentStep(status.current_step);
        }
      } catch (err) {
        console.warn("Poll error:", err);
      }
    }, POLL_INTERVAL_MS);

    return () => clearInterval(intervalId);
  }, [phase, jobId, fetchInventionIdea, loadResults]);

  // ── Init UI (brief spinner while first poll resolves) ──
  if (phase === "init") {
    return (
      <main className="min-h-[calc(100vh-65px)] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
      </main>
    );
  }

  // ── Polling UI ──
  if (phase === "polling") {
    const realStepIdx = STEPS.findIndex((s) => s.key === currentStep);
    const displayStepIdx = Math.max(
      simulatedStepIdx,
      realStepIdx < 0 ? 0 : realStepIdx
    );

    return (
      <main className="min-h-[calc(100vh-65px)] flex flex-col items-center justify-center px-4 py-16">
        <div className="w-full max-w-2xl text-center mb-10">
          <h1 className="text-2xl font-bold text-white mb-2">
            Analyzing your invention...
          </h1>
          <p className="text-gray-500 text-sm">
            This usually takes 15–60 seconds.
          </p>
        </div>
        <Stepper stepIdx={displayStepIdx} />
      </main>
    );
  }

  // ── Loading results from Supabase ──
  if (phase === "loading_results") {
    return (
      <main className="min-h-[calc(100vh-65px)] flex items-center justify-center px-4">
        <div className="text-center max-w-lg">
          <div className="w-8 h-8 border-2 border-blue-400 border-t-transparent rounded-full animate-spin mx-auto mb-5" />
          <h2 className="text-white font-semibold text-lg mb-2">
            Compiling your results...
          </h2>
          {inventionIdea && (
            <p className="text-gray-500 text-sm leading-relaxed">
              &ldquo;
              {inventionIdea.length > 100
                ? inventionIdea.slice(0, 100) + "..."
                : inventionIdea}
              &rdquo;
            </p>
          )}
        </div>
      </main>
    );
  }

  // ── Error UI ──
  if (phase === "failed") {
    return (
      <main className="min-h-[calc(100vh-65px)] flex items-center justify-center px-4">
        <div className="max-w-md w-full bg-red-950 border border-red-800 rounded-xl p-8 text-center">
          <div className="text-red-400 text-4xl mb-4">✕</div>
          <h2 className="text-white font-bold text-lg mb-2">Analysis Failed</h2>
          <p className="text-red-300 text-sm mb-6">
            {errorMessage ?? "An unknown error occurred."}
          </p>
          <a
            href="/"
            className="inline-block bg-gray-800 hover:bg-gray-700 text-gray-200 text-sm px-4 py-2 rounded-lg transition-colors"
          >
            ← Try again
          </a>
        </div>
      </main>
    );
  }

  // ── Completed Results ──
  if (!searchResult || !searchMeta) return null;

  const gaps = parseWhiteSpace(searchResult.white_space_analysis ?? "");
  const clusters: Cluster[] = Array.isArray(searchResult.clusters)
    ? searchResult.clusters
    : [];
  const citationLinks = searchResult.citation_links ?? [];

  return (
    <main className="min-h-[calc(100vh-65px)] px-4 py-10 max-w-6xl mx-auto">
      {/* Header */}
      <header className="mb-10">
        <p className="text-gray-500 text-sm mb-2">
          {new Date(searchMeta.created_at).toLocaleDateString("en-US", {
            month: "long",
            day: "numeric",
            year: "numeric",
          })}
        </p>
        <h1 className="text-2xl font-bold text-white mb-4 max-w-3xl leading-snug">
          &ldquo;
          {searchMeta.invention_idea.length > 140
            ? searchMeta.invention_idea.slice(0, 140) + "..."
            : searchMeta.invention_idea}
          &rdquo;
        </h1>
        <div className="flex gap-2 flex-wrap">
          {clusters.length > 0 && (
            <span className="bg-blue-900 text-blue-300 text-xs px-3 py-1 rounded-full border border-blue-700">
              {clusters.length} Prior Art Cluster{clusters.length !== 1 ? "s" : ""}
            </span>
          )}
          {gaps.length > 0 && (
            <span className="bg-purple-900 text-purple-300 text-xs px-3 py-1 rounded-full border border-purple-700">
              {gaps.length} White Space Opportunit{gaps.length !== 1 ? "ies" : "y"}
            </span>
          )}
        </div>
      </header>

      {/* Section 1: White Space */}
      {gaps.length > 0 && (
        <section className="mb-12">
          <h2 className="text-xl font-bold text-white mb-5">
            White Space Opportunities
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {gaps.map((gap, idx) => (
              <WhiteSpaceCard key={idx} gap={gap} />
            ))}
          </div>
        </section>
      )}

      {/* Section 1.5: Technology Trends */}
      {clusters.some((c) => (c.filing_trend ?? []).length >= 2) && (
        <section className="mb-12">
          <h2 className="text-xl font-bold text-white mb-5">Technology Trends</h2>
          <div className="flex flex-row gap-4 overflow-x-auto pb-2">
            {clusters
              .filter((c) => (c.filing_trend ?? []).length >= 2)
              .map((cluster, idx) => (
                <TrendCard key={idx} cluster={cluster} />
              ))}
          </div>
        </section>
      )}

      {/* Section 2: Prior Art Clusters */}
      {clusters.length > 0 && (
        <section className="mb-12">
          <h2 className="text-xl font-bold text-white mb-5">
            Prior Art Clusters
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {clusters.map((cluster, idx) => (
              <ClusterCard key={idx} cluster={cluster} />
            ))}
          </div>
        </section>
      )}

      {/* Section 2.5: Patent Relationship Graph */}
      {citationLinks.length > 0 && (
        <section className="mb-12 print:hidden">
          <h2 className="text-xl font-bold text-white mb-2">
            Patent Relationship Graph
          </h2>
          <p className="text-gray-500 text-sm mb-5">
            Click a node to see patent details. Node colors match clusters above.
          </p>
          <PatentGraphSection
            clusters={clusters}
            citationLinks={citationLinks}
            onNodeClick={setSelectedNode}
          />
        </section>
      )}

      {/* Node side panel */}
      {selectedNode && (
        <NodeSidePanel
          node={selectedNode}
          clusters={clusters}
          onClose={() => setSelectedNode(null)}
        />
      )}

      {/* Section 3: Full Brief */}
      <section className="mb-12">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-xl font-bold text-white">Full Analysis Brief</h2>
          <div className="flex items-center gap-2 print:hidden">
            <button
              onClick={handleCopyLink}
              className="text-sm text-gray-400 hover:text-gray-200 border border-gray-700 hover:border-gray-500 px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1.5"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
                <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
              </svg>
              {copied ? "Copied!" : "Copy link"}
            </button>
            <button
              onClick={handlePrint}
              className="text-sm text-gray-400 hover:text-gray-200 border border-gray-700 hover:border-gray-500 px-3 py-1.5 rounded-lg transition-colors"
            >
              Print / Save PDF
            </button>
          </div>
        </div>
        <div className="bg-gray-900 border border-gray-700 rounded-xl p-8 brief-content">
          <MarkdownRenderer content={searchResult.white_space_analysis ?? ""} />
        </div>
      </section>

      {/* Print-only footer */}
      <div className="print-footer hidden">
        Generated by PatentMapper — patentmapper.com — Not legal advice
      </div>

      {/* Footer nav */}
      <div className="border-t border-gray-800 pt-8 flex flex-col sm:flex-row items-center gap-4 print:hidden">
        <a
          href="/"
          className="w-full sm:w-auto bg-blue-600 hover:bg-blue-500 text-white font-semibold py-3 px-8 rounded-xl transition-colors text-center"
        >
          + New Analysis
        </a>
        <a
          href="/dashboard"
          className="text-gray-500 hover:text-gray-300 text-sm transition-colors"
        >
          View all searches →
        </a>
      </div>
    </main>
  );
}
