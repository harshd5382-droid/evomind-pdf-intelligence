"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useVisiblePolling } from "@/lib/usePolling";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api, apiOr, safeWriteText, uploadPdf } from "@/lib/api";
import { FolderUpload } from "@/components/folder-upload";
import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip,
} from "recharts";
import { FileUp, FolderUp, ListOrdered, Cpu, FolderOpen, Zap, Eye } from "lucide-react";
import { formatRelative } from "@/lib/utils";

type Snap = {
  score: number; documents: number; chunks: number; questions: number;
  answered: number; unresolved: number; insights: number; concepts: number;
  hypotheses: number; contradictions: number; avg_confidence: number;
};
type FeedItem = { type: string; [k: string]: any };
type UsageRow  = { provider: string; model: string; purpose: string; calls: number; input_tokens: number; output_tokens: number; avg_latency_ms: number };
type UsageSummary = { hours: number; totals: { calls: number; input_tokens: number; output_tokens: number }; by_purpose: UsageRow[] };
type JobStats = { queued_db: number; running: number; succeeded: number; failed: number; queue_depth: number; active_workers: number };
type Diagnostics = {
  runtime_mode: string;
  issues: { level: string; message: string }[];
  dependencies: {
    database: { backend: string; reachable: boolean };
    feed: { mode: string };
    vector_store: { mode: string };
    graph: { mode: string; reachable?: boolean; configured?: boolean };
  };
  integrity: {
    counts: { repairable_failed_jobs: number; failed_jobs: number };
  };
};
type AutopilotStatus = {
  enabled: boolean; running: boolean; last_runs: Record<string, number>;
  intervals: Record<string, number>; solve_batch: number;
};
type WatcherStatus = {
  enabled: boolean; running: boolean; watching: string;
  interval_sec: number; stable_sec: number; seen_in_process: number;
};

/* ── event-type colour dots ─────────────────────────── */
const EV_COLOR: Record<string, string> = {
  "document.ingested":    "text-accent2",
  "question.generated":   "text-violet-400",
  "answer.created":       "text-ok",
  "learner.reflected":    "text-pink-400",
  "insight.created":      "text-accent",
  "hypothesis.created":   "text-fuchsia-400",
  "contradiction.detected":"text-bad",
  "cycle.started":        "text-sub",
  "cycle.completed":      "text-sub",
  "daily.started":        "text-sub",
  "daily.completed":      "text-sub",
};

/* ── circular SVG arc around the score ─────────────── */
function ScoreArc({ value, max = 100 }: { value: number; max?: number }) {
  const r    = 72;
  const circ = 2 * Math.PI * r;
  const pct  = Math.min(Math.max(value / max, 0), 1);
  const offset = circ * (1 - pct);

  return (
    <svg
      width="180" height="180"
      viewBox="0 0 180 180"
      className="absolute inset-0 pointer-events-none"
    >
      {/* Outer dashed decoration */}
      <circle
        cx="90" cy="90" r={r + 10}
        fill="none" stroke="#1B3257" strokeWidth="0.5"
        strokeDasharray="2 7" opacity="0.7"
      />
      {/* Full track */}
      <circle
        cx="90" cy="90" r={r}
        fill="none" stroke="#1B3257" strokeWidth="1"
      />
      {/* Progress arc (starts from top via rotate -90) */}
      <circle
        cx="90" cy="90" r={r}
        fill="none"
        stroke="#C9A227"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeDasharray={circ}
        strokeDashoffset={offset}
        transform="rotate(-90 90 90)"
        style={{ transition: "stroke-dashoffset 1.2s cubic-bezier(0.4,0,0.2,1)" }}
      />
    </svg>
  );
}

/* ── custom recharts tooltip ────────────────────────── */
function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="card px-3 py-2 text-xs">
      <div className="font-mono text-dim mb-0.5">{label}</div>
      <div className="font-mono text-accent">{payload[0].value?.toFixed(2)}</div>
    </div>
  );
}

export default function Dashboard() {
  const [metrics,  setMetrics]  = useState<{ current: Snap; history: any[] } | null>(null);
  const [feed,     setFeed]     = useState<FeedItem[]>([]);
  const [docs,     setDocs]     = useState<any[]>([]);
  const [usage,    setUsage]    = useState<UsageSummary | null>(null);
  const [jobStats, setJobStats] = useState<JobStats | null>(null);
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null);
  const [autopilot, setAutopilot] = useState<AutopilotStatus | null>(null);
  const [watcher,  setWatcher]  = useState<WatcherStatus | null>(null);
  const [busy,     setBusy]     = useState(false);
  const [nudging,  setNudging]  = useState(false);
  const [folderOpen, setFolderOpen] = useState(false);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "unavailable">("idle");
  const fileRef = useRef<HTMLInputElement>(null);

  async function refresh() {
    const [m, d, f, u, js, ap, wt, diag] = await Promise.all([
      apiOr<{ current: Snap; history: any[] }>("/metrics", { current: {
        score: 0, documents: 0, chunks: 0, questions: 0, answered: 0, unresolved: 0,
        insights: 0, concepts: 0, hypotheses: 0, contradictions: 0, avg_confidence: 0,
      }, history: [] }),
      apiOr<any[]>("/documents", []),
      apiOr<FeedItem[]>("/feed/recent?limit=30", []),
      apiOr<UsageSummary>("/usage/summary?hours=24", {
        hours: 24,
        totals: { calls: 0, input_tokens: 0, output_tokens: 0 },
        by_purpose: [],
      }),
      apiOr<JobStats>("/jobs/stats", {
        queued_db: 0, running: 0, succeeded: 0, failed: 0, queue_depth: 0, active_workers: 0,
      }),
      apiOr<AutopilotStatus | null>("/autopilot/status", null),
      apiOr<WatcherStatus | null>("/folder-watcher/status", null),
      apiOr<Diagnostics | null>("/diagnostics", null),
    ]);
    setMetrics(m); setDocs(d); setFeed(f); setUsage(u); setJobStats(js); setAutopilot(ap); setWatcher(wt); setDiagnostics(diag);
  }

  useVisiblePolling(refresh, 8_000);

  async function handleUpload(file: File) {
    setBusy(true);
    try { await uploadPdf(file); await refresh(); } finally { setBusy(false); }
  }

  async function nudgeAutopilot() {
    setNudging(true);
    try {
      await Promise.all([
        api("/folder-watcher/scan-now", { method: "POST" }).catch(() => null),
        api("/autopilot/run-now",       { method: "POST" }).catch(() => null),
      ]);
      await refresh();
    } finally { setNudging(false); }
  }

  async function copyDropPath() {
    if (!watcher?.watching) return;
    const ok = await safeWriteText(watcher.watching);
    setCopyState(ok ? "copied" : "unavailable");
    window.setTimeout(() => setCopyState("idle"), 1800);
  }

  const snap   = metrics?.current;
  const series = (metrics?.history ?? []).map((h) => ({
    t:     new Date(h.t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    score: h.value,
  }));

  const statRow = [
    { label: "Documents",     value: snap?.documents    ?? "—" },
    { label: "Chunks",        value: snap?.chunks       ?? "—" },
    { label: "Questions",     value: snap?.questions    ?? "—" },
    { label: "Answered",      value: snap?.answered     ?? "—" },
    { label: "Concepts",      value: snap?.concepts     ?? "—" },
    { label: "Hypotheses",    value: snap?.hypotheses   ?? "—" },
    { label: "Contradictions",value: snap?.contradictions ?? "—" },
    { label: "Unresolved",    value: snap?.unresolved   ?? "—" },
  ];

  const hasQueue = jobStats && (jobStats.queue_depth > 0 || jobStats.active_workers > 0 || jobStats.running > 0);

  return (
    <div className="min-h-screen">
      {/* ── Top header bar ──────────────────────────────── */}
      <header className="flex items-center justify-between px-8 pt-8 pb-6">
        <div>
          <h1 className="font-display text-3xl font-light tracking-tight text-ink leading-none">
            Research Dashboard
          </h1>
          <p className="font-mono text-[11px] text-dim mt-2 tracking-wide">
            Autonomous PDF intelligence — your only job is to upload.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Autopilot status pill */}
          <div className="flex items-center gap-2 px-3 h-8 border border-accent/40 bg-accent/8">
            <Cpu className="w-3.5 h-3.5 text-accent" />
            <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-accent">
              {autopilot?.running ? "Autopilot · engaged" : autopilot?.enabled ? "Autopilot · idle" : "Autopilot · off"}
            </span>
            {autopilot?.running && <span className="live-dot" />}
          </div>
          <input
            ref={fileRef} type="file" accept="application/pdf" hidden
            onChange={(e) => e.target.files?.[0] && handleUpload(e.target.files[0])}
          />
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => fileRef.current?.click()}>
            <FileUp className="w-3.5 h-3.5" /> Upload PDF
          </Button>
          <Button size="sm" disabled={busy} onClick={() => setFolderOpen(true)}>
            <FolderUp className="w-3.5 h-3.5" /> Upload Folder
          </Button>
        </div>
      </header>

      {folderOpen && <FolderUpload onClose={() => setFolderOpen(false)} onDone={refresh} />}

      {/* ── Auto-ingest drop folder banner ─────────────── */}
      {watcher?.enabled && (
        <div className="mx-8 mb-3 flex items-center gap-3 px-4 py-3 border border-accent2/30 bg-accent2/5 font-mono text-[11px]">
          <FolderOpen className="w-4 h-4 text-accent2 shrink-0" />
          <div className="flex-1 min-w-0 flex items-center gap-3">
            <span className="text-accent2 uppercase tracking-[0.18em] text-[9px]">Drop folder</span>
            <code
              onClick={copyDropPath}
              title="Click to copy"
              className="text-ink truncate cursor-pointer hover:text-accent transition-colors max-w-[520px]"
            >
              {watcher.watching}
            </code>
            <span className="text-dim">·</span>
            <span className={watcher.running ? "text-ok" : "text-bad"}>
              {watcher.running ? "watching" : "stopped"}
            </span>
            {copyState === "copied" && <span className="text-ok">· copied</span>}
            {copyState === "unavailable" && <span className="text-warn">· clipboard unavailable in this browser</span>}
            {watcher.seen_in_process > 0 && (
              <>
                <span className="text-dim">·</span>
                <span className="text-sub">{watcher.seen_in_process} picked up</span>
              </>
            )}
          </div>
          <button
            onClick={nudgeAutopilot}
            disabled={nudging}
            className="flex items-center gap-1.5 px-3 h-7 border border-accent/40 hover:bg-accent/10 transition-colors text-accent text-[10px] uppercase tracking-[0.16em] disabled:opacity-50"
          >
            <Zap className="w-3 h-3" /> {nudging ? "running…" : "Run now"}
          </button>
        </div>
      )}

      {diagnostics && (diagnostics.issues.length > 0 || diagnostics.integrity.counts.repairable_failed_jobs > 0) && (
        <div className="mx-8 mb-4 px-4 py-3 border border-warn/30 bg-warn/10 font-mono text-[11px]">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="text-warn uppercase tracking-[0.18em] text-[9px]">
              Runtime · {diagnostics.runtime_mode}
            </span>
            <span className="text-sub">
              db {diagnostics.dependencies.database.backend}
            </span>
            <span className="text-sub">
              feed {diagnostics.dependencies.feed.mode}
            </span>
            <span className="text-sub">
              vectors {diagnostics.dependencies.vector_store.mode}
            </span>
            <span className="text-sub">
              graph {diagnostics.dependencies.graph.reachable === false && diagnostics.dependencies.graph.configured ? "sql-fallback" : diagnostics.dependencies.graph.mode}
            </span>
            {diagnostics.integrity.counts.repairable_failed_jobs > 0 && (
              <span className="text-bad">
                {diagnostics.integrity.counts.repairable_failed_jobs} repairable failed jobs
              </span>
            )}
          </div>
          {diagnostics.issues.length > 0 && (
            <div className="mt-2 text-sub">
              {diagnostics.issues.slice(0, 3).map((issue) => issue.message).join(" · ")}
            </div>
          )}
        </div>
      )}

      {/* Queue banner */}
      {hasQueue && (
        <div className="mx-8 mb-4 flex items-center gap-3 px-4 py-2 border border-accent/25 bg-accent/8 font-mono text-[11px]">
          <ListOrdered className="w-3.5 h-3.5 text-accent shrink-0" />
          <span className="text-accent">Ingest queue active</span>
          <span className="text-dim">·</span>
          <span className="text-sub"><span className="text-ink">{jobStats!.queue_depth}</span> waiting</span>
          <span className="text-dim">·</span>
          <span className="text-sub"><span className="text-ink">{jobStats!.active_workers}</span> workers</span>
          <span className="text-dim">·</span>
          <span className="text-ok">{jobStats!.succeeded} done</span>
          {jobStats!.failed > 0 && (
            <><span className="text-dim">·</span><span className="text-bad">{jobStats!.failed} failed</span></>
          )}
        </div>
      )}

      <hr className="rule mx-8" />

      {/* ── Intelligence score hero + trend chart ──────── */}
      <section className="flex gap-0 px-8 py-8">
        {/* Score column */}
        <div className="w-64 shrink-0 flex flex-col items-center justify-center relative">
          <div className="relative w-[180px] h-[180px] flex items-center justify-center">
            <ScoreArc value={snap?.score ?? 0} />
            <div className="text-center z-10">
              <div className="font-display text-6xl font-light text-accent score-glow leading-none">
                {snap ? snap.score.toFixed(1) : "—"}
              </div>
              <div className="font-mono text-[9px] tracking-[0.2em] text-dim mt-2 uppercase">
                IQ Score
              </div>
            </div>
          </div>
          <div className="mt-4 text-center space-y-1">
            <div className="font-mono text-[10px] text-dim">
              avg confidence{" "}
              <span className="text-sub">
                {snap ? `${(snap.avg_confidence * 100).toFixed(0)}%` : "—"}
              </span>
            </div>
            <div className="font-mono text-[10px] text-dim">
              {snap?.insights ?? "—"} insights generated
            </div>
          </div>
        </div>

        {/* Divider */}
        <div className="w-px bg-border mx-6 self-stretch" />

        {/* Trend chart */}
        <div className="flex-1 min-w-0">
          <div className="font-mono text-[9px] uppercase tracking-[0.2em] text-dim mb-4">
            Intelligence Trend
          </div>
          {series.length === 0 ? (
            <div className="h-48 flex items-center justify-center font-mono text-[11px] text-dim">
              No history yet — run an autonomous cycle to begin.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={190}>
              <AreaChart data={series} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="scoreGrad" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%"   stopColor="#C9A227" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="#C9A227" stopOpacity={0}    />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="t"
                  stroke="#3D5A7A"
                  tick={{ fontSize: 10, fontFamily: "'JetBrains Mono', monospace", fill: "#3D5A7A" }}
                  axisLine={{ stroke: "#1B3257" }}
                  tickLine={false}
                />
                <YAxis
                  stroke="#3D5A7A"
                  tick={{ fontSize: 10, fontFamily: "'JetBrains Mono', monospace", fill: "#3D5A7A" }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip content={<ChartTooltip />} />
                <Area
                  type="monotone"
                  dataKey="score"
                  stroke="#C9A227"
                  strokeWidth={1.5}
                  fill="url(#scoreGrad)"
                  dot={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>
      </section>

      <hr className="rule mx-8" />

      {/* ── Stat strip ──────────────────────────────────── */}
      <section className="flex px-8 py-6 gap-0">
        {statRow.map((s, i) => (
          <div key={s.label} className="flex-1 text-center relative">
            {i > 0 && (
              <div className="absolute left-0 inset-y-0 w-px bg-border" />
            )}
            <div className="font-display text-2xl font-light text-ink">
              {typeof s.value === "number" ? s.value.toLocaleString() : s.value}
            </div>
            <div className="font-mono text-[9px] uppercase tracking-[0.16em] text-dim mt-1">
              {s.label}
            </div>
          </div>
        ))}
      </section>

      <hr className="rule mx-8" />

      {/* ── Documents + Live Feed ───────────────────────── */}
      <section className="flex gap-0 px-8 py-8">
        {/* Documents table */}
        <div className="flex-[2] min-w-0">
          <div className="font-mono text-[9px] uppercase tracking-[0.22em] text-dim mb-5">
            Documents
          </div>
          {docs.length === 0 ? (
            <div className="font-mono text-[11px] text-dim">
              No documents yet — upload a PDF to begin.
            </div>
          ) : (
            <div className="max-h-[480px] overflow-y-auto pr-1">
              <table className="w-full text-[12.5px]">
                <thead className="sticky top-0 bg-bg z-10">
                  <tr>
                    {["Title", "Subject", "Pages", "Status", "Added"].map((h) => (
                      <th
                        key={h}
                        className="text-left pb-2.5 pr-4 font-mono text-[9px] uppercase tracking-[0.16em] text-dim border-b border-border font-normal bg-bg"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {docs.map((d) => (
                    <tr
                      key={d.id}
                      className="border-b border-border/50 hover:bg-white/[0.02] transition-colors"
                    >
                      <td className="py-2.5 pr-4">
                        <Link
                          href={`/documents/${d.id}`}
                          className="text-ink hover:text-accent transition-colors truncate block max-w-[220px]"
                        >
                          {d.title}
                        </Link>
                      </td>
                      <td className="pr-4 text-sub truncate max-w-[120px]">
                        {d.subject_area || "—"}
                      </td>
                      <td className="pr-4 font-mono text-sub">{d.page_count}</td>
                      <td className="pr-4">
                        <Badge variant={d.status === "ready" ? "answered" : "open"}>
                          {d.status}
                        </Badge>
                      </td>
                      <td className="font-mono text-dim text-[11px]">{formatRelative(d.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="font-mono text-[9px] uppercase tracking-[0.18em] text-dim mt-3 pt-2 border-t border-border/40">
                {docs.length} {docs.length === 1 ? "document" : "documents"}
              </div>
            </div>
          )}
        </div>

        {/* Vertical divider */}
        <div className="w-px bg-border mx-8 self-stretch" />

        {/* Live feed — terminal style */}
        <div className="w-72 shrink-0">
          <div className="flex items-center gap-2 mb-5">
            <span className="font-mono text-[9px] uppercase tracking-[0.22em] text-dim">
              Research Log
            </span>
            <span className="live-dot" />
          </div>
          <div className="space-y-0 max-h-[400px] overflow-y-auto">
            {feed.length === 0 && (
              <div className="font-mono text-[11px] text-dim">Waiting for activity…</div>
            )}
            {feed.map((ev, i) => {
              const colorCls = EV_COLOR[ev.type] ?? "text-sub";
              const text = ev.text || ev.title || ev.statement || ev.preview
                || JSON.stringify(ev).slice(0, 120);
              return (
                <div
                  key={ev._event_id ?? `${ev.type}-${ev._t ?? ev.timestamp ?? i}`}
                  className="feed-row py-1.5 border-b border-border/30 group animate-fade-in"
                  style={{ animationDelay: `${i * 20}ms` }}
                >
                  <div className="flex items-baseline gap-2">
                    <span className={`text-[9px] uppercase tracking-[0.1em] shrink-0 ${colorCls}`}>
                      {ev.type.replace(".", " ")}
                    </span>
                    <span className="font-mono text-[9px] text-dim ml-auto shrink-0">
                      {new Date(ev._t || ev.timestamp || Date.now()).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                    </span>
                  </div>
                  <div className="font-mono text-[11px] text-sub mt-0.5 line-clamp-2 leading-[1.5]">
                    {text}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ── LLM Usage ───────────────────────────────────── */}
      {usage && usage.totals.calls > 0 && (
        <>
          <hr className="rule mx-8" />
          <section className="px-8 py-6">
            <div className="font-mono text-[9px] uppercase tracking-[0.22em] text-dim mb-4">
              LLM Usage · 24 h
            </div>
            <div className="flex items-start gap-10">
              <div className="flex gap-8">
                {[
                  { label: "Calls",  value: usage.totals.calls.toLocaleString() },
                  { label: "In",     value: usage.totals.input_tokens.toLocaleString() },
                  { label: "Out",    value: usage.totals.output_tokens.toLocaleString() },
                ].map((m) => (
                  <div key={m.label}>
                    <div className="font-display text-xl font-light text-ink">{m.value}</div>
                    <div className="font-mono text-[9px] uppercase tracking-[0.15em] text-dim mt-0.5">{m.label}</div>
                  </div>
                ))}
              </div>
              <div className="border-l border-border pl-8 flex-1 grid grid-cols-2 gap-x-8 gap-y-1 max-h-28 overflow-y-auto">
                {usage.by_purpose.map((r, i) => (
                  <div key={i} className="flex items-baseline justify-between gap-2">
                    <span className="font-mono text-[10px] text-dim truncate">{r.purpose}</span>
                    <span className="font-mono text-[10px] text-sub shrink-0">
                      {r.input_tokens.toLocaleString()} → {r.output_tokens.toLocaleString()}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </section>
        </>
      )}

      {/* Bottom padding */}
      <div className="h-12" />
    </div>
  );
}
