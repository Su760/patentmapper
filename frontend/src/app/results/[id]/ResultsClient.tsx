"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import {
  getJobStatus,
  getClaimsAnalysis,
  ideateWhiteSpace,
  WhiteSpaceIdea,
  analyzeClaimsRequest,
  ClaimResult,
} from "@/lib/api";
import { RESULTS_POLLING } from "@/lib/results-config";
import { startJobPolling } from "@/lib/poll-job";
import { createClient } from "@/lib/supabase";
import { useAuth } from "@/lib/auth-context";
import { DEMO_JOB_ID, DEMO_META, DEMO_RESULTS } from "@/lib/demo";
import MarkdownRenderer from "@/components/MarkdownRenderer";
import "./print.css";

// ─── Types ───────────────────────────────────────────────────────────────────

type Phase =
  | "init"
  | "polling"
  | "loading_results"
  | "completed"
  | "failed"
  | "unavailable";

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
  final_report?: string | null;
  retrieval_outcome?: string | null;
  coverage_warnings?: string[];
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
  { key: "finalizing", label: "Saving results..." },
  { key: "done", label: "Complete!" },
] as const;

const CLUSTER_COLORS = [
  "#3b82f6",
  "#8b5cf6",
  "#22c55e",
  "#eab308",
  "#ec4899",
  "#06b6d4",
];

// ─── Visual Helpers ───────────────────────────────────────────────────────────

function viabilityToTier(v: string): "high" | "medium" | "low" {
  const lower = v.toLowerCase();
  if (lower.startsWith("high")) return "high";
  if (lower.startsWith("medium")) return "medium";
  return "low";
}

function Sparkline({
  series,
  color,
  width = 192,
  height = 36,
}: {
  series: number[];
  color: string;
  width?: number;
  height?: number;
}) {
  const max = Math.max(...series);
  const min = Math.min(...series);
  const range = max - min || 1;
  const step = width / (series.length - 1);
  const pts = series
    .map((v, i) => `${i * step},${height - ((v - min) / range) * height}`)
    .join(" ");
  const area = `0,${height} ${pts} ${width},${height}`;
  const gradId = `spark-${color.replace("#", "")}`;
  const lastY = height - ((series[series.length - 1] - min) / range) * height;
  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.35" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={area} fill={`url(#${gradId})`} />
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" />
      <circle
        cx={width}
        cy={lastY}
        r="2.5"
        fill={color}
        stroke="var(--surface)"
        strokeWidth="1.5"
      />
    </svg>
  );
}

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
        nodeMap.set(pid, {
          id: pid,
          clusterIdx: idx,
          clusterName: cluster.theme_name,
        });
      }
    });
  });

  // Include any node referenced in links even if not in clusters
  citationLinks.forEach(({ source, target }) => {
    if (!nodeMap.has(source))
      nodeMap.set(source, { id: source, clusterIdx: 0, clusterName: "" });
    if (!nodeMap.has(target))
      nodeMap.set(target, { id: target, clusterIdx: 0, clusterName: "" });
  });

  return {
    nodes: Array.from(nodeMap.values()),
    links: citationLinks.map((l) => ({
      source: l.source,
      target: l.target,
      strength: l.strength,
    })),
  };
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function Stepper({ stepIdx }: { stepIdx: number }) {
  return (
    <div style={{ width: "100%", maxWidth: 480, margin: "0 auto" }}>
      {STEPS.map((step, idx) => {
        const isDone = idx < stepIdx;
        const isActive = idx === stepIdx;

        return (
          <div
            key={step.key}
            aria-current={isActive ? "step" : undefined}
            style={{
              display: "flex",
              alignItems: "flex-start",
              gap: 16,
              marginBottom: 16,
            }}
          >
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
              }}
            >
              <div
                style={{
                  width: 28,
                  height: 28,
                  borderRadius: "50%",
                  border: `2px solid ${isDone ? "var(--green)" : isActive ? "var(--blue)" : "var(--border-strong)"}`,
                  background: isDone ? "var(--green)" : "transparent",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                }}
              >
                {isDone ? (
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="white"
                    strokeWidth={3}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M5 13l4 4L19 7"
                    />
                  </svg>
                ) : isActive ? (
                  <div
                    style={{
                      width: 10,
                      height: 10,
                      background: "var(--blue)",
                      borderRadius: "50%",
                    }}
                    className="animate-pulse"
                  />
                ) : (
                  <div
                    style={{
                      width: 8,
                      height: 8,
                      background: "var(--border-strong)",
                      borderRadius: "50%",
                    }}
                  />
                )}
              </div>
              {idx < STEPS.length - 1 && (
                <div
                  style={{
                    width: 1,
                    height: 16,
                    marginTop: 4,
                    background: isDone ? "var(--green)" : "var(--border)",
                  }}
                />
              )}
            </div>
            <p
              style={{
                fontSize: 14,
                paddingTop: 4,
                color: isDone
                  ? "var(--text-3)"
                  : isActive
                    ? "var(--blue)"
                    : "var(--border-strong)",
                textDecoration: isDone ? "line-through" : "none",
              }}
            >
              {step.label}
            </p>
          </div>
        );
      })}
    </div>
  );
}

function WhiteSpaceCard({
  gap,
  index,
  idea,
  isIdeating,
  ideationError,
  onIdeate,
}: {
  gap: WhiteSpaceGap;
  index: number;
  idea?: WhiteSpaceIdea;
  isIdeating: boolean;
  ideationError?: string;
  onIdeate: () => void;
}) {
  const tier = viabilityToTier(gap.viability);
  const badgeClass =
    tier === "high" ? "green" : tier === "medium" ? "yellow" : "red";
  const barWidth = tier === "high" ? "85%" : tier === "medium" ? "55%" : "25%";

  return (
    <article className="pm-ws-card print:break-inside-avoid" data-tier={tier}>
      <div className="pm-ws-head">
        <div>
          <div className="pm-ws-eyebrow">
            GAP {String(index + 1).padStart(2, "0")} · White Space
          </div>
          <h3 className="pm-ws-title">{gap.title}</h3>
        </div>
        <span className={`pm-badge ${badgeClass}`}>{gap.viability}</span>
      </div>
      <p className="pm-ws-desc">{gap.description}</p>
      {ideationError && (
        <p role="alert">Idea generation failed: {ideationError}</p>
      )}
      <div className="pm-ws-foot">
        <div className="pm-ws-score">
          <span style={{ color: "var(--text-3)" }}>viability</span>
          <div className="pm-ws-bar">
            <i style={{ width: barWidth }}></i>
          </div>
        </div>
        {!idea && (
          <button
            onClick={onIdeate}
            disabled={isIdeating}
            className="pm-btn purple sm"
          >
            {isIdeating ? (
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <svg
                  className="animate-spin"
                  width="12"
                  height="12"
                  viewBox="0 0 24 24"
                  fill="none"
                >
                  <circle
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                    opacity="0.25"
                  />
                  <path
                    fill="currentColor"
                    opacity="0.75"
                    d="M4 12a8 8 0 018-8v8z"
                  />
                </svg>
                Generating...
              </span>
            ) : (
              "Generate idea ✨"
            )}
          </button>
        )}
      </div>

      {idea && (
        <div
          style={{
            background: "rgba(139,92,246,0.08)",
            border: "1px solid rgba(139,92,246,0.3)",
            borderRadius: 10,
            padding: 16,
            marginTop: 12,
          }}
        >
          <p style={{ fontWeight: 600, color: "var(--purple)" }}>
            {idea.invention_name}
          </p>
          <p style={{ fontSize: 13, color: "var(--text-2)", marginTop: 4 }}>
            {idea.one_liner}
          </p>
          <p
            style={{
              fontSize: 11,
              color: "var(--text-3)",
              marginTop: 8,
              textTransform: "uppercase",
              letterSpacing: "0.06em",
            }}
          >
            Mechanism
          </p>
          <p style={{ fontSize: 12, color: "var(--text-2)" }}>
            {idea.mechanism}
          </p>
          <p
            style={{
              fontSize: 11,
              color: "var(--text-3)",
              marginTop: 8,
              textTransform: "uppercase",
              letterSpacing: "0.06em",
            }}
          >
            Key Differentiators
          </p>
          <ul style={{ fontSize: 12, color: "var(--text-2)", paddingLeft: 16 }}>
            {idea.key_differentiators.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ul>
          <p
            style={{
              fontSize: 11,
              color: "var(--text-3)",
              marginTop: 8,
              textTransform: "uppercase",
              letterSpacing: "0.06em",
            }}
          >
            Why Novel
          </p>
          <p style={{ fontSize: 12, color: "var(--text-2)" }}>
            {idea.why_novel}
          </p>
        </div>
      )}
    </article>
  );
}

function TrendCard({ cluster, color }: { cluster: Cluster; color: string }) {
  const trend = cluster.filing_trend ?? [];
  const series = trend.map((t) => t.count);
  const delta = series[series.length - 1] - series[0];
  const direction =
    delta > series[0] * 0.2 ? "up" : delta < -series[0] * 0.2 ? "down" : "flat";
  const pct = series[0] > 0 ? Math.round((delta / series[0]) * 100) : 0;
  const deltaLabel =
    direction === "up" ? `+${pct}%` : direction === "down" ? `${pct}%` : "0%";
  const firstYear = trend[0]?.year;
  const lastYear = trend[trend.length - 1]?.year;

  return (
    <div className="pm-trend-card">
      <div className="pm-trend-head">
        <div className="pm-trend-name">
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: 999,
              background: color,
              boxShadow: `0 0 6px ${color}`,
              display: "inline-block",
              flexShrink: 0,
            }}
          />
          {cluster.theme_name}
        </div>
        <span className={`pm-trend-arrow ${direction}`}>
          {direction === "up" ? "↗" : direction === "down" ? "↘" : "→"}{" "}
          {deltaLabel}
        </span>
      </div>
      <Sparkline series={series} color={color} width={192} height={36} />
      <div className="pm-trend-foot">
        <span>
          {firstYear} → {lastYear}
        </span>
        <span>filing trend</span>
      </div>
    </div>
  );
}

function ClusterCard({ cluster, color }: { cluster: Cluster; color: string }) {
  const maxCount = Math.max(
    ...(cluster.top_assignees ?? []).map((a) => a.count),
    1,
  );
  return (
    <article
      className="pm-cluster print:break-inside-avoid"
      style={{ "--cdot": color } as React.CSSProperties}
    >
      <div className="pm-cluster-head">
        <span className="pm-cluster-dot"></span>
        <span className="pm-cluster-name">{cluster.theme_name}</span>
        <span className="pm-cluster-meta">{cluster.patent_ids.length} pat</span>
      </div>
      <p className="pm-cluster-desc">{cluster.description}</p>
      {cluster.ipc_codes && cluster.ipc_codes.length > 0 && (
        <>
          <div className="pm-cluster-section-label">IPC / CPC</div>
          <div className="pm-chip-row">
            {cluster.ipc_codes.map((code) => (
              <span key={code} className="pm-chip ipc">
                {code}
              </span>
            ))}
          </div>
        </>
      )}
      {cluster.top_assignees && cluster.top_assignees.length > 0 && (
        <>
          <div className="pm-cluster-section-label">Top assignees</div>
          <div className="pm-players">
            {cluster.top_assignees.map((a) => (
              <div key={a.name}>
                <div className="pm-player">
                  <span className="pm-player-name">{a.name}</span>
                  <span className="pm-player-count">{a.count} patents</span>
                </div>
                <div className="pm-player-bar">
                  <i style={{ width: `${(a.count / maxCount) * 100}%` }}></i>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
      <div className="pm-cluster-foot">
        {cluster.patent_ids.slice(0, 4).map((pid) => (
          <a
            key={pid}
            href={`https://patents.google.com/patent/${pid}`}
            target="_blank"
            rel="noopener noreferrer"
            className="pm-chip tiny"
          >
            {pid}
          </a>
        ))}
      </div>
    </article>
  );
}

interface SimLink {
  source: string;
  target: string;
  strength: number;
}

function CitationGraphSVG({
  nodes,
  links,
  onNodeClick,
}: {
  nodes: GraphNode[];
  links: SimLink[];
  onNodeClick: (node: GraphNode) => void;
}) {
  const HEIGHT = 400;
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  const [positions, setPositions] = useState<
    Map<string, { x: number; y: number }>
  >(new Map());
  const rafRef = useRef<number>(0);
  const iterRef = useRef(0);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    setWidth(el.offsetWidth || 800);
    const ro = new ResizeObserver(() => setWidth(el.offsetWidth || 800));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (nodes.length === 0) return;
    cancelAnimationFrame(rafRef.current);
    iterRef.current = 0;

    const W = width;
    const H = HEIGHT;
    const MAX_ITER = 250;
    const n = nodes.length;

    const idxMap = new Map<string, number>(
      nodes.map((node, i) => [node.id, i]),
    );

    const px = new Float64Array(n);
    const py = new Float64Array(n);
    const vx = new Float64Array(n);
    const vy = new Float64Array(n);
    nodes.forEach((_, i) => {
      const angle = (i / n) * 2 * Math.PI;
      const r = Math.min(W, H) * 0.3;
      px[i] = W / 2 + r * Math.cos(angle) + (Math.random() - 0.5) * 10;
      py[i] = H / 2 + r * Math.sin(angle) + (Math.random() - 0.5) * 10;
    });

    const edgeList: { si: number; ti: number; strength: number }[] = [];
    links.forEach((l) => {
      const si = idxMap.get(l.source);
      const ti = idxMap.get(l.target);
      if (si !== undefined && ti !== undefined) {
        edgeList.push({ si, ti, strength: l.strength });
      }
    });

    const REPULSION = 1500;
    const SPRING_K = 0.04;
    const SPRING_REST = 80;
    const CENTER_K = 0.008;
    const DAMPING = 0.8;
    const fx = new Float64Array(n);
    const fy = new Float64Array(n);

    function tick() {
      if (iterRef.current >= MAX_ITER) return;
      iterRef.current++;

      fx.fill(0);
      fy.fill(0);

      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          const dx = px[j] - px[i];
          const dy = py[j] - py[i];
          const d2 = dx * dx + dy * dy + 1;
          const d = Math.sqrt(d2);
          const f = REPULSION / d2;
          fx[i] -= f * (dx / d);
          fy[i] -= f * (dy / d);
          fx[j] += f * (dx / d);
          fy[j] += f * (dy / d);
        }
      }

      for (const { si, ti, strength } of edgeList) {
        const dx = px[ti] - px[si];
        const dy = py[ti] - py[si];
        const d = Math.sqrt(dx * dx + dy * dy) + 0.01;
        const f = SPRING_K * (d - SPRING_REST) * strength;
        fx[si] += f * (dx / d);
        fy[si] += f * (dy / d);
        fx[ti] -= f * (dx / d);
        fy[ti] -= f * (dy / d);
      }

      for (let i = 0; i < n; i++) {
        fx[i] += (W / 2 - px[i]) * CENTER_K;
        fy[i] += (H / 2 - py[i]) * CENTER_K;
        vx[i] = (vx[i] + fx[i]) * DAMPING;
        vy[i] = (vy[i] + fy[i]) * DAMPING;
        px[i] = Math.max(8, Math.min(W - 8, px[i] + vx[i]));
        py[i] = Math.max(8, Math.min(H - 8, py[i] + vy[i]));
      }

      const posMap = new Map<string, { x: number; y: number }>();
      nodes.forEach((node, i) => posMap.set(node.id, { x: px[i], y: py[i] }));
      setPositions(new Map(posMap));

      rafRef.current = requestAnimationFrame(tick);
    }

    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [nodes, links, width]);

  return (
    <div
      ref={containerRef}
      className="w-full h-[400px] rounded-xl overflow-hidden border border-gray-700 bg-gray-950"
    >
      <svg width={width} height={HEIGHT} style={{ display: "block" }}>
        {links.map((link, i) => {
          const src = positions.get(link.source);
          const tgt = positions.get(link.target);
          if (!src || !tgt) return null;
          return (
            <line
              key={i}
              x1={src.x}
              y1={src.y}
              x2={tgt.x}
              y2={tgt.y}
              stroke="rgba(100,116,139,0.4)"
              strokeWidth={link.strength * 2}
            />
          );
        })}
        {nodes.map((node) => {
          const pos = positions.get(node.id);
          if (!pos) return null;
          const color = CLUSTER_COLORS[node.clusterIdx % CLUSTER_COLORS.length];
          return (
            <g
              key={node.id}
              transform={`translate(${pos.x},${pos.y})`}
              onClick={() => onNodeClick(node)}
              style={{ cursor: "pointer" }}
            >
              <circle r={5} fill={color} />
              <title>{node.id}</title>
            </g>
          );
        })}
      </svg>
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
  const graphData = buildGraphData(clusters, citationLinks);
  return (
    <CitationGraphSVG
      nodes={graphData.nodes}
      links={graphData.links}
      onNodeClick={onNodeClick}
    />
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
      style={{
        position: "fixed",
        right: 16,
        top: "25%",
        width: 288,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 12,
        padding: 20,
        boxShadow: "0 24px 48px rgba(0,0,0,0.5)",
        zIndex: 50,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          marginBottom: 16,
        }}
      >
        <span
          style={{
            fontSize: 11,
            color: "var(--text-3)",
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.08em",
          }}
        >
          Patent
        </span>
        <button
          onClick={onClose}
          aria-label="Close"
          style={{
            color: "var(--text-3)",
            background: "none",
            border: "none",
            cursor: "pointer",
            fontSize: 18,
            lineHeight: 1,
            padding: 0,
          }}
        >
          ×
        </button>
      </div>
      <p
        style={{
          fontFamily: "var(--font-mono)",
          color: "var(--text)",
          fontSize: 13,
          fontWeight: 600,
          marginBottom: 12,
          wordBreak: "break-all",
        }}
      >
        {node.id}
      </p>
      {cluster && (
        <div style={{ marginBottom: 16 }}>
          <span style={{ fontSize: 11, color: "var(--text-3)" }}>Cluster</span>
          <p style={{ color: "var(--text-2)", fontSize: 12, marginTop: 4 }}>
            {cluster.theme_name}
          </p>
        </div>
      )}
      <a
        href={`https://patents.google.com/patent/${node.id}`}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          display: "block",
          color: "var(--blue)",
          fontSize: 12,
          fontWeight: 500,
          textDecoration: "none",
        }}
      >
        View on Google Patents →
      </a>
    </div>
  );
}

// ─── Claim Analysis Components ───────────────────────────────────────────────

function overlapBadgeStyle(level: ClaimResult["overlap_level"]): {
  background: string;
  color: string;
  border: string;
} {
  switch (level) {
    case "high":
      return {
        background: "rgba(239,68,68,0.12)",
        color: "#ef4444",
        border: "1px solid rgba(239,68,68,0.3)",
      };
    case "medium":
      return {
        background: "rgba(234,179,8,0.12)",
        color: "#ca8a04",
        border: "1px solid rgba(234,179,8,0.3)",
      };
    case "low":
    case "none":
      return {
        background: "rgba(34,197,94,0.12)",
        color: "#16a34a",
        border: "1px solid rgba(34,197,94,0.3)",
      };
  }
}

function ClaimCard({ claim }: { claim: ClaimResult }) {
  const badge = overlapBadgeStyle(claim.overlap_level);
  return (
    <div className="pm-cluster">
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: 8,
          marginBottom: 12,
          flexWrap: "wrap",
        }}
      >
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--text-3)",
            background: "var(--surface-2)",
            border: "1px solid var(--border)",
            borderRadius: 4,
            padding: "2px 6px",
          }}
        >
          {claim.patent_id}
        </span>
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            borderRadius: 4,
            padding: "2px 8px",
            textTransform: "uppercase",
            letterSpacing: "0.05em",
            ...badge,
          }}
        >
          {claim.overlap_level} overlap
        </span>
      </div>
      <p className="pm-cluster-name" style={{ marginBottom: 12 }}>
        {claim.title}
      </p>
      <p className="pm-cluster-section-label" style={{ marginBottom: 6 }}>
        Likely Claims
      </p>
      <ul
        style={{
          margin: "0 0 12px 0",
          paddingLeft: 16,
          fontSize: 12,
          color: "var(--text-2)",
          lineHeight: 1.6,
        }}
      >
        {claim.likely_claims.map((c, i) => (
          <li key={i}>{c}</li>
        ))}
      </ul>
      <p className="pm-cluster-section-label" style={{ marginBottom: 4 }}>
        Overlap
      </p>
      <p style={{ fontSize: 13, color: "var(--text-2)", marginBottom: 12 }}>
        {claim.overlap_explanation}
      </p>
      <p className="pm-cluster-section-label" style={{ marginBottom: 4 }}>
        Your Differentiators
      </p>
      <p style={{ fontSize: 13, color: "var(--green)" }}>
        {claim.differentiators}
      </p>
    </div>
  );
}

// ─── Main Client Component ────────────────────────────────────────────────────

export default function ResultsClient({ jobId }: { jobId: string }) {
  const { user, loading: authLoading } = useAuth();
  const userId = user?.id;
  const isDemo = jobId === DEMO_JOB_ID;
  const accessScope = useRef("");
  accessScope.current = `${jobId}:${userId ?? "signed-out"}`;
  const [renderScope, setRenderScope] = useState("");
  const [phase, setPhase] = useState<Phase>("init");
  const [currentStep, setCurrentStep] = useState<string | null>(null);
  const [pollNotice, setPollNotice] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [inventionIdea, setInventionIdea] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [searchMeta, setSearchMeta] = useState<SearchMeta | null>(null);
  const [searchResult, setSearchResult] = useState<SearchResult | null>(null);
  const [copied, setCopied] = useState(false);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [ideating, setIdeating] = useState<Record<string, boolean>>({});
  const pendingIdeations = useRef(new Set<string>());
  const [ideationErrors, setIdeationErrors] = useState<Record<string, string>>(
    {},
  );
  const [ideas, setIdeas] = useState<Record<string, WhiteSpaceIdea>>({});
  const [analyzingClaims, setAnalyzingClaims] = useState(false);
  const [claimsAnalysis, setClaimsAnalysis] = useState<ClaimResult[] | null>(
    null,
  );
  const [claimsError, setClaimsError] = useState<string | null>(null);

  const [claimsCacheReady, setClaimsCacheReady] = useState(false);
  const lifecycle = useRef<AbortController | null>(null);
  const epoch = useRef(0);
  const claimsPending = useRef(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout>>();
  const claimsSectionRef = useRef<HTMLElement | null>(null);

  const loadCachedClaims = useCallback(
    async (signal: AbortSignal, version: number) => {
      if (signal.aborted) return;
      const scope = accessScope.current;
      const controller = new AbortController();
      const abort = () => controller.abort();
      signal.addEventListener("abort", abort, { once: true });
      const timeout = setTimeout(abort, RESULTS_POLLING.timeoutMs);
      const current = () =>
        !signal.aborted &&
        epoch.current === version &&
        scope === accessScope.current;
      setClaimsCacheReady(false);
      setClaimsError(null);
      try {
        const { claims } = await getClaimsAnalysis(jobId, controller.signal);
        if (!current() || signal.aborted) return;
        setClaimsAnalysis(claims);
        setClaimsCacheReady(true);
      } catch (error) {
        if (!current() || signal.aborted) return;
        setClaimsError(
          controller.signal.aborted
            ? "Saved claims timed out. Retry saved claims; no generation was requested."
            : error instanceof Error
              ? error.message
              : "Could not load saved claims.",
        );
      } finally {
        clearTimeout(timeout);
        signal.removeEventListener("abort", abort);
      }
    },
    [jobId],
  );

  async function handleIdeate(gap: WhiteSpaceGap) {
    const scope = accessScope.current;
    const version = epoch.current;
    const key = `${version}:${scope}:${gap.title}`;
    if (pendingIdeations.current.has(key)) return;
    pendingIdeations.current.add(key);
    setIdeating((prev) => ({ ...prev, [gap.title]: true }));
    setIdeationErrors((prev) => ({ ...prev, [gap.title]: "" }));
    try {
      const idea = await ideateWhiteSpace(
        jobId,
        gap.title,
        gap.description,
        lifecycle.current?.signal,
      );
      if (scope !== accessScope.current || version !== epoch.current) return;
      setIdeas((prev) => ({ ...prev, [gap.title]: idea }));
    } catch (e) {
      if (scope === accessScope.current && version === epoch.current)
        setIdeationErrors((prev) => ({
          ...prev,
          [gap.title]:
            e instanceof Error
              ? e.message
              : "Try again. If this continues, reload or sign in again.",
        }));
    } finally {
      pendingIdeations.current.delete(key);
      if (scope === accessScope.current && version === epoch.current)
        setIdeating((prev) => ({ ...prev, [gap.title]: false }));
    }
  }

  async function handleAnalyzeClaims() {
    const scope = accessScope.current;
    if (claimsPending.current || !claimsCacheReady) return;
    claimsPending.current = true;
    const version = epoch.current;
    setAnalyzingClaims(true);
    setClaimsError(null);
    try {
      const { claims } = await analyzeClaimsRequest(
        jobId,
        lifecycle.current?.signal,
      );
      if (scope !== accessScope.current || version !== epoch.current) return;
      setClaimsAnalysis(claims);
    } catch (e) {
      if (scope === accessScope.current && version === epoch.current)
        setClaimsError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      if (scope === accessScope.current && version === epoch.current) {
        claimsPending.current = false;
        setAnalyzingClaims(false);
      }
    }
  }

  function handlePrint() {
    const prev = document.title;
    const idea = searchMeta?.invention_idea ?? "";
    document.title = `PatentMapper - ${idea.slice(0, 60)}`;
    window.print();
    document.title = prev;
  }

  async function handleCopyLink() {
    const version = epoch.current;
    const scope = accessScope.current;
    await navigator.clipboard.writeText(window.location.href);
    if (version !== epoch.current || scope !== accessScope.current) return;
    setCopied(true);
    clearTimeout(copyTimer.current);
    copyTimer.current = setTimeout(() => setCopied(false), 2000);
  }

  useEffect(() => {
    if (authLoading && !isDemo) return;
    const version = ++epoch.current;
    const scope = accessScope.current;
    const controller = new AbortController();
    lifecycle.current = controller;
    const current = () =>
      !controller.signal.aborted &&
      version === epoch.current &&
      scope === accessScope.current;
    setRenderScope(scope);
    setSearchMeta(null);
    setSearchResult(null);
    setClaimsAnalysis(null);
    setClaimsCacheReady(false);
    setIdeas({});
    setInventionIdea(null);
    setSelectedNode(null);
    setIdeating({});
    setIdeationErrors({});
    setAnalyzingClaims(false);
    claimsPending.current = false;
    setClaimsError(null);
    setPollNotice(null);
    setErrorMessage(null);
    setCurrentStep(null);
    setPhase("init");
    let stop = () => {};
    if (!isDemo && !userId) {
      setErrorMessage(
        "Sign in to access this private analysis. A job link alone does not grant access.",
      );
      setPhase("unavailable");
    } else {
      stop = startJobPolling({
        read: (signal) => getJobStatus(jobId, signal),
        onStatus: async (status, signal) => {
          if (!current() || signal.aborted) return;
          setPollNotice(null);
          setCurrentStep(status.current_step);
          if (status.status === "processing") {
            setPhase("polling");
            return;
          }
          if (status.status === "failed") {
            setErrorMessage(status.error_message ?? "Analysis failed.");
            setPhase("failed");
            return;
          }
          setPhase("loading_results");
          if (isDemo) {
            setSearchMeta(DEMO_META);
            setSearchResult(DEMO_RESULTS);
          } else {
            const client = createClient();
            const [search, result] = await Promise.all([
              client
                .from("searches")
                .select("invention_idea, created_at")
                .eq("id", jobId)
                .abortSignal(signal)
                .single(),
              client
                .from("search_results")
                .select(
                  "clusters, white_space_analysis, final_report, citation_links, retrieval_outcome, coverage_warnings",
                )
                .eq("search_id", jobId)
                .abortSignal(signal)
                .single(),
            ]);
            if (!current() || signal.aborted) return;
            if (search.error || result.error)
              throw new Error(
                "Saved results could not be loaded. Retry status to reload them without generating anything.",
              );
            setSearchMeta(search.data as SearchMeta);
            setInventionIdea(search.data.invention_idea);
            setSearchResult(result.data as SearchResult);
          }
          if (!current() || signal.aborted) return;
          setPhase("completed");
          // Viewing saved claims never calls the paid generation endpoint.
          void loadCachedClaims(controller.signal, version);
        },
        onError: (message, stopped, unauthorized) => {
          if (!current()) return;
          if (stopped) {
            setErrorMessage(message);
            setPhase("unavailable");
          } else {
            setPollNotice(
              `Status unavailable: ${message} Retrying automatically (read only).`,
            );
            setPhase("polling");
          }
          if (unauthorized) {
            setSearchResult(null);
            setClaimsAnalysis(null);
          }
        },
      });
    }
    return () => {
      epoch.current = version + 1;
      controller.abort();
      stop();
      clearTimeout(copyTimer.current);
    };
  }, [jobId, userId, authLoading, isDemo, reload, loadCachedClaims]);

  async function retryCachedClaims() {
    const controller = lifecycle.current;
    if (!controller) return;
    await loadCachedClaims(controller.signal, epoch.current);
  }

  // ── Init UI (brief spinner while first poll resolves) ──
  if (renderScope !== accessScope.current) return null;
  if (phase === "init") {
    return (
      <main
        style={{
          minHeight: "calc(100vh - 65px)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div
          style={{
            width: 32,
            height: 32,
            border: "2px solid var(--blue)",
            borderTopColor: "transparent",
            borderRadius: "50%",
            animation: "spin 0.7s linear infinite",
          }}
        />
      </main>
    );
  }

  // ── Polling UI ──
  if (phase === "polling") {
    const realStepIdx = STEPS.findIndex((s) => s.key === currentStep);
    const displayStepIdx = realStepIdx;

    return (
      <main
        style={{
          minHeight: "calc(100vh - 65px)",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: "64px 16px",
        }}
      >
        {pollNotice && (
          <p role="alert" style={{ padding: 16 }}>
            {pollNotice}
          </p>
        )}
        {!currentStep && <p>Waiting for a saved backend stage.</p>}
        <div
          style={{
            maxWidth: 672,
            width: "100%",
            textAlign: "center",
            marginBottom: 40,
          }}
        >
          <h1
            style={{
              fontSize: 24,
              fontWeight: 700,
              color: "var(--text)",
              marginBottom: 8,
            }}
          >
            Analyzing your invention...
          </h1>
          <p style={{ color: "var(--text-3)", fontSize: 14 }}>
            Progress reflects stages saved by the server.
          </p>
        </div>
        <Stepper stepIdx={displayStepIdx} />
      </main>
    );
  }

  // ── Loading results from Supabase ──
  if (phase === "loading_results") {
    return (
      <main
        style={{
          minHeight: "calc(100vh - 65px)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "0 16px",
        }}
      >
        <div style={{ textAlign: "center", maxWidth: 480 }}>
          <div
            style={{
              width: 32,
              height: 32,
              border: "2px solid var(--blue)",
              borderTopColor: "transparent",
              borderRadius: "50%",
              animation: "spin 0.7s linear infinite",
              margin: "0 auto 20px",
            }}
          />
          <h2
            style={{
              color: "var(--text)",
              fontWeight: 600,
              fontSize: 18,
              marginBottom: 8,
            }}
          >
            Loading saved results...
          </h2>
          {inventionIdea && (
            <p
              style={{ color: "var(--text-3)", fontSize: 14, lineHeight: 1.6 }}
            >
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
  if (phase === "failed" || phase === "unavailable") {
    return (
      <main
        style={{
          minHeight: "calc(100vh - 65px)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "0 16px",
        }}
      >
        <div
          style={{
            maxWidth: 448,
            width: "100%",
            background: "color-mix(in srgb, var(--red) 10%, var(--bg))",
            border: "1px solid color-mix(in srgb, var(--red) 40%, transparent)",
            borderRadius: 12,
            padding: 32,
            textAlign: "center",
          }}
        >
          <div style={{ color: "var(--red)", fontSize: 36, marginBottom: 16 }}>
            ✕
          </div>
          <h2
            style={{
              color: "var(--text)",
              fontWeight: 700,
              fontSize: 18,
              marginBottom: 8,
            }}
          >
            {phase === "failed" ? "Analysis failed" : "Analysis unavailable"}
          </h2>
          <p style={{ color: "var(--text-2)", fontSize: 14, marginBottom: 24 }}>
            {errorMessage ?? "An unknown error occurred."}
          </p>
          <button
            className="pm-btn sm"
            onClick={() => setReload((value) => value + 1)}
          >
            Retry status
          </button>
          <p>Checks saved status only; no paid work is started.</p>
          <a href="/auth">Sign in</a> · <a href="/">New analysis</a>
        </div>
      </main>
    );
  }

  // ── Completed Results ──
  if (!searchResult || !searchMeta) return null;

  const insufficient =
    searchResult.retrieval_outcome === "insufficient_evidence";
  const gaps = insufficient
    ? []
    : parseWhiteSpace(searchResult.white_space_analysis ?? "");
  const clusters: Cluster[] = Array.isArray(searchResult.clusters)
    ? searchResult.clusters
    : [];
  const citationLinks = searchResult.citation_links ?? [];
  const totalPatents = clusters.flatMap((c) => c.patent_ids).length;

  return (
    <div className="pm" style={{ minHeight: "100%" }}>
      {isDemo && (
        <p role="status" style={{ padding: 16, color: "var(--text-2)" }}>
          Synthetic demo — fixed sample data. No patent search or AI generation
          was performed. <a href="/auth">Sign in</a> for a private analysis.
        </p>
      )}
      {/* Sticky header bar */}
      <div className="pm-sticky-bar">
        <div className="pm-sticky-left">
          <a href="/dashboard" className="pm-sticky-back">
            ← Dashboard
          </a>
          <span style={{ color: "var(--border-strong)" }}>/</span>
          <span className="pm-sticky-title" title={searchMeta.invention_idea}>
            {searchMeta.invention_idea.length > 60
              ? searchMeta.invention_idea.slice(0, 60) + "..."
              : searchMeta.invention_idea}
          </span>
        </div>
        <div className="pm-sticky-meta print:hidden">
          <span className="pm-pill">
            <span className="dot" style={{ background: "var(--blue)" }}></span>
            {clusters.length} clusters
          </span>
          <span className="pm-pill">
            <span
              className="dot"
              style={{ background: "var(--purple)" }}
            ></span>
            {gaps.length} gaps
          </span>
          <span className="pm-pill">
            <span className="dot" style={{ background: "var(--green)" }}></span>
            {totalPatents} patents
          </span>
          <span
            style={{
              width: 1,
              height: 16,
              background: "var(--border)",
              margin: "0 4px",
            }}
          ></span>
          <button className="pm-btn sm print:hidden" onClick={handlePrint}>
            ⤓ Export
          </button>
          <button className="pm-btn sm print:hidden" onClick={handleCopyLink}>
            {copied ? "Copied!" : "Share"}
          </button>
          {!insufficient && (
            <button
              className="pm-btn sm print:hidden"
              onClick={() =>
                claimsSectionRef.current?.scrollIntoView({ behavior: "smooth" })
              }
            >
              ⚖ Claims
            </button>
          )}
        </div>
      </div>
      {insufficient && (
        <p role="status" style={{ padding: 32 }}>
          Insufficient evidence: retrieval succeeded but no usable patents were
          found. No gap, report, or claims conclusions were generated.
        </p>
      )}
      {(searchResult.coverage_warnings ?? []).map((warning, index) => (
        <p role="status" key={index} style={{ padding: "8px 32px" }}>
          {warning}
        </p>
      ))}

      {/* Section 01: White Space Opportunities */}
      {gaps.length > 0 && (
        <section className="pm-section">
          <div className="pm-section-head">
            <div className="pm-section-title">
              <span className="num">01</span>
              <h2>White space opportunities</h2>
            </div>
            <div className="pm-section-aside">
              <span>{gaps.length} gaps identified · ranked by viability</span>
            </div>
          </div>
          <div className="pm-ws-grid">
            {gaps.map((gap, idx) => (
              <WhiteSpaceCard
                key={gap.title}
                gap={gap}
                index={idx}
                idea={ideas[gap.title]}
                isIdeating={!!ideating[gap.title]}
                ideationError={ideationErrors[gap.title]}
                onIdeate={() => handleIdeate(gap)}
              />
            ))}
          </div>
        </section>
      )}

      {/* Section 02: Technology Trends */}
      {clusters.some((c) => (c.filing_trend ?? []).length >= 2) && (
        <>
          <section className="pm-section" style={{ paddingBottom: 0 }}>
            <div className="pm-section-head">
              <div className="pm-section-title">
                <span className="num">02</span>
                <h2>Technology trends</h2>
              </div>
              <div className="pm-section-aside">
                <span style={{ fontFamily: "var(--font-mono)" }}>
                  filing · rolling
                </span>
              </div>
            </div>
          </section>
          <div
            className="pm-trends"
            style={{
              paddingLeft: 32,
              paddingRight: 32,
              maxWidth: 1320,
              margin: "0 auto",
            }}
          >
            {clusters
              .filter((c) => (c.filing_trend ?? []).length >= 2)
              .map((cluster, idx) => (
                <TrendCard
                  key={cluster.theme_name}
                  cluster={cluster}
                  color={CLUSTER_COLORS[idx % CLUSTER_COLORS.length]}
                />
              ))}
          </div>
        </>
      )}

      {/* Section 03: Prior Art Clusters */}
      {clusters.length > 0 && (
        <section className="pm-section">
          <div className="pm-section-head">
            <div className="pm-section-title">
              <span className="num">03</span>
              <h2>Prior art clusters</h2>
            </div>
            <div className="pm-section-aside">
              <span>{clusters.length} clusters</span>
            </div>
          </div>
          <div className="pm-cluster-grid">
            {clusters.map((cluster, idx) => (
              <ClusterCard
                key={cluster.theme_name}
                cluster={cluster}
                color={CLUSTER_COLORS[idx % CLUSTER_COLORS.length]}
              />
            ))}
          </div>
        </section>
      )}

      {/* Section 04: Patent Relationship Graph */}
      {citationLinks.length > 0 && (
        <>
          <section
            className="pm-section print:hidden"
            style={{ paddingBottom: 0 }}
          >
            <div className="pm-section-head">
              <div className="pm-section-title">
                <span className="num">04</span>
                <h2>Patent relationship graph</h2>
              </div>
              <div className="pm-section-aside">
                <span>{citationLinks.length} inferred relationships</span>
              </div>
            </div>
          </section>
          <div className="pm-graph-panel print:hidden">
            <div className="pm-graph-grid"></div>
            <div className="pm-graph-head">
              <div className="pm-graph-legend">
                {clusters.map((c, i) => (
                  <div key={c.theme_name} className="pm-graph-legend-row">
                    <span
                      className="ldot"
                      style={{
                        background: CLUSTER_COLORS[i % CLUSTER_COLORS.length],
                      }}
                    ></span>
                    {c.theme_name}
                  </div>
                ))}
              </div>
              <div className="pm-graph-controls">
                <button className="pm-graph-ctl">+</button>
                <button className="pm-graph-ctl">−</button>
                <button className="pm-graph-ctl">⤢</button>
              </div>
            </div>
            <PatentGraphSection
              clusters={clusters}
              citationLinks={citationLinks}
              onNodeClick={setSelectedNode}
            />
          </div>
        </>
      )}

      {/* Node side panel */}
      {selectedNode && (
        <NodeSidePanel
          node={selectedNode}
          clusters={clusters}
          onClose={() => setSelectedNode(null)}
        />
      )}

      {/* Section 05: Full Analysis Brief */}
      <section className="pm-section">
        <div className="pm-section-head">
          <div className="pm-section-title">
            <span className="num">05</span>
            <h2>Full analysis brief</h2>
          </div>
          <div className="pm-section-aside print:hidden">
            <button className="pm-btn sm" onClick={handleCopyLink}>
              {copied ? "Copied!" : "Copy link"}
            </button>
            <button className="pm-btn sm" onClick={handlePrint}>
              ⤓ Print / Save PDF
            </button>
          </div>
        </div>
        <div
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 12,
            padding: 32,
          }}
        >
          {searchResult.final_report ? (
            <MarkdownRenderer content={searchResult.final_report} />
          ) : (
            <p>
              {insufficient
                ? "A full report is unavailable because there is insufficient evidence."
                : "No saved full report is available for this older analysis."}
            </p>
          )}
        </div>
        <div
          className="print:block"
          style={{
            display: "none",
            marginTop: 24,
            color: "var(--text-3)",
            fontSize: 12,
          }}
        >
          Generated by PatentMapper — patentmapper.com — Not legal advice
        </div>
      </section>

      {/* Section 06: Claim Analysis */}
      {!insufficient && (
        <section className="pm-section" ref={claimsSectionRef}>
          <div className="pm-section-head">
            <div className="pm-section-title">
              <span className="num">06</span>
              <h2>Claim analysis</h2>
            </div>
            <div className="pm-section-aside">
              <span>
                Prior art overlap with your invention — not legal advice
              </span>
            </div>
          </div>
          <p>
            {isDemo
              ? "Fixed synthetic sample; no usage consumed."
              : "Uses 1 claims allowance per generation or regeneration. Failed paid attempts also count. Reading saved claims is free."}
          </p>
          {claimsError && (
            <p role="alert">Claim analysis unavailable: {claimsError}</p>
          )}
          {!claimsCacheReady ? (
            <>
              {!claimsError && <p>Loading saved claims...</p>}
              {claimsError && (
                <button className="pm-btn" onClick={retryCachedClaims}>
                  Retry saved claims
                </button>
              )}
            </>
          ) : (
            <>
              {claimsAnalysis === null && (
                <p>
                  No saved claims analysis. Generate it explicitly when you are
                  ready.
                </p>
              )}
              {claimsAnalysis?.length === 0 && (
                <p>The saved claims analysis contains no claims.</p>
              )}
              <button
                className="pm-btn"
                disabled={analyzingClaims}
                onClick={handleAnalyzeClaims}
              >
                {analyzingClaims
                  ? "Generating claims..."
                  : claimsAnalysis === null
                    ? "Generate claims"
                    : "Regenerate claims"}
              </button>
            </>
          )}
          <div className="pm-cluster-grid">
            {(claimsAnalysis ?? []).map((claim) => (
              <ClaimCard key={claim.patent_id} claim={claim} />
            ))}
          </div>
          <p
            style={{
              textAlign: "center",
              color: "var(--text-3)",
              fontSize: 12,
              marginTop: 24,
              fontFamily: "var(--font-mono)",
            }}
          >
            This analysis is AI-generated from patent abstracts only and does
            not constitute legal advice. Consult a patent attorney for formal
            freedom-to-operate analysis.
          </p>
        </section>
      )}

      {/* Footer nav */}
      <div
        className="print:hidden"
        style={{
          borderTop: "1px solid var(--border)",
          padding: "32px 32px",
          display: "flex",
          gap: 12,
          alignItems: "center",
        }}
      >
        <a href="/" className="pm-btn">
          + New Analysis
        </a>
        <a
          href="/dashboard"
          style={{
            color: "var(--text-3)",
            fontSize: 14,
            textDecoration: "none",
          }}
        >
          View all searches →
        </a>
      </div>
    </div>
  );
}
