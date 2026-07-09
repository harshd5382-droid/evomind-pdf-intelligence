"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { api, apiOr } from "@/lib/api";
import { pct } from "@/lib/format";
import { formatRelative } from "@/lib/utils";
import { Download, FileText, Gauge, Loader2 } from "lucide-react";

type Insight = { id: string; title: string; body: string; kind: string; created_at: string };

type EvalSnap = {
  faithfulness: number;
  grounded_rate: number;
  citation_coverage: number;
  sample_size: number;
};
type EvalHistItem = { t: string; value: number; extra: EvalSnap };
type FeedbackSummary = { up: number; down: number; total: number; approval_rate: number };

export default function ReportsPage() {
  const [insights, setInsights] = useState<Insight[]>([]);
  const [open,     setOpen]     = useState<Insight | null>(null);

  useEffect(() => {
    apiOr<Insight[]>("/insights", []).then(setInsights);
  }, []);

  function downloadMarkdown(i: Insight) {
    const md  = `# ${i.title}\n\n_Generated ${i.created_at}_\n\n${i.body}\n`;
    const url = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
    const a   = document.createElement("a");
    a.href = url;
    a.download = `${i.title.replace(/[^a-z0-9]+/gi, "_").slice(0, 60)}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="px-8 py-8 max-w-[1300px]">
      <header className="mb-8">
        <div className="flex items-center gap-3 mb-1">
          <FileText className="w-5 h-5 text-accent" />
          <h1 className="font-display text-3xl font-light text-ink">Reports & Insights</h1>
        </div>
        <p className="font-mono text-[11px] text-dim mt-2 tracking-wide">
          Cross-document syntheses, taxonomies, and discovered patterns.
        </p>
      </header>

      <hr className="rule mb-8" />

      <QualityPanel />

      <div className="grid lg:grid-cols-3 gap-8">
        {/* Insight list */}
        <div className="lg:col-span-1">
          <div className="font-mono text-[9px] uppercase tracking-[0.22em] text-dim mb-4">
            Insights — {insights.length}
          </div>
          <div className="space-y-1.5 max-h-[640px] overflow-y-auto pr-1">
            {insights.length === 0 && (
              <div className="font-mono text-[11px] text-dim border border-border/50 py-8 text-center">
                Run an autonomous cycle to produce insights.
              </div>
            )}
            {insights.map((i) => (
              <button
                key={i.id}
                onClick={() => setOpen(i)}
                className={[
                  "w-full text-left border p-3 transition-colors",
                  open?.id === i.id
                    ? "border-accent/40 bg-accent/8"
                    : "border-border bg-panel/60 hover:border-border/80",
                ].join(" ")}
              >
                <div className="font-mono text-[9px] text-dim mb-1.5 uppercase tracking-[0.1em]">
                  {formatRelative(i.created_at)} · {i.kind}
                </div>
                <div className="text-[12.5px] text-ink font-medium leading-snug">{i.title}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Insight body */}
        <div className="lg:col-span-2 border border-border bg-panel/60 p-6 min-h-[400px]">
          {open ? (
            <>
              <div className="flex items-start justify-between gap-4 mb-6">
                <div>
                  <div className="font-mono text-[9px] uppercase tracking-[0.15em] text-dim mb-2">
                    {open.kind} · {formatRelative(open.created_at)}
                  </div>
                  <h2 className="font-display text-xl font-light text-ink leading-snug">
                    {open.title}
                  </h2>
                </div>
                <Button size="sm" variant="ghost" onClick={() => downloadMarkdown(open)} className="shrink-0">
                  <Download className="w-3.5 h-3.5" /> Download MD
                </Button>
              </div>
              <hr className="rule mb-5" />
              <article className="font-mono text-[12px] text-sub leading-[1.8] whitespace-pre-wrap max-h-[520px] overflow-y-auto">
                {open.body}
              </article>
            </>
          ) : (
            <div className="h-full flex items-center justify-center font-mono text-[11px] text-dim">
              Select an insight to read.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function QualityPanel() {
  const [snap, setSnap] = useState<EvalSnap | null>(null);
  const [fb, setFb] = useState<FeedbackSummary | null>(null);
  const [running, setRunning] = useState(false);

  async function load() {
    const [hist, summary] = await Promise.all([
      apiOr<EvalHistItem[]>("/eval/history", []),
      apiOr<FeedbackSummary>("/feedback/summary", { up: 0, down: 0, total: 0, approval_rate: 0 }),
    ]);
    setSnap(hist.length ? hist[hist.length - 1].extra : null);
    setFb(summary);
  }
  useEffect(() => { load(); }, []);

  async function runEval() {
    setRunning(true);
    try {
      await api("/eval/run", { method: "POST", body: JSON.stringify({ sample_size: 20 }) });
      await load();
    } catch {
      /* surfaced by the empty state; auth may be required */
    } finally {
      setRunning(false);
    }
  }


  return (
    <section className="mb-8 border border-border bg-panel/60 p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Gauge className="w-3.5 h-3.5 text-accent" />
          <span className="font-mono text-[9px] uppercase tracking-[0.22em] text-dim">
            Answer quality
          </span>
        </div>
        <Button size="sm" variant="ghost" onClick={runEval} disabled={running}>
          {running ? <Loader2 className="w-3 h-3 animate-spin" /> : <Gauge className="w-3 h-3" />}
          Run eval
        </Button>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Tile label="Faithfulness" value={pct(snap?.faithfulness)} />
        <Tile label="Grounded rate" value={pct(snap?.grounded_rate)} />
        <Tile label="Citation coverage" value={pct(snap?.citation_coverage)} />
        <Tile
          label="Approval"
          value={fb && fb.total ? pct(fb.approval_rate) : "—"}
          sub={fb ? `${fb.up}↑ / ${fb.down}↓` : undefined}
        />
      </div>
      {!snap && (
        <p className="font-mono text-[10px] text-dim mt-4">
          No eval run yet — click “Run eval” to score recent answers for groundedness.
        </p>
      )}
    </section>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="border border-border/60 bg-bg/40 p-3">
      <div className="font-mono text-[9px] uppercase tracking-[0.12em] text-dim mb-1.5">{label}</div>
      <div className="font-display text-2xl font-light text-ink">{value}</div>
      {sub && <div className="font-mono text-[9px] text-dim mt-1">{sub}</div>}
    </div>
  );
}
