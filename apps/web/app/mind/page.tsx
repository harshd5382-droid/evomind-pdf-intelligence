"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useVisiblePolling } from "@/lib/usePolling";
import { Brain, MessageCircle, HelpCircle, AlertTriangle, Eye, Sparkles, RefreshCw, BookOpen, Compass, GraduationCap, Pencil } from "lucide-react";

type Belief = { id: string; statement: string; rationale: string; supporting: number; opposing: number };
type OpenQ  = { id: string; text: string; priority: number };
type Confusion = { id: string; summary: string; severity: number };

type Identity = {
  narrative: string;
  beliefs: Belief[];
  open_questions: OpenQ[];
  active_topics: string[];
  confusion: Confusion[];
  confidence: number;
  cycles: number;
  updated_at: string | null;
};

type MemoryStats = {
  total: number;
  embedded: number;
  pending: number;
  by_source: Record<string, number>;
};

type JournalEntry = {
  id: string;
  body: string;
  mood: string | null;
  topics: string[];
  referenced: { kind: string; id: string }[];
  created_at: string | null;
};

type Gap = {
  id: string;
  topic: string;
  kind: "uncovered_concept" | "weak_hypothesis" | "low_confidence" | "open_contradiction";
  score: number;
  rationale: string;
  addressed: boolean;
};

type TrainingStatus = {
  stage: "accumulating" | "early" | "ready" | "mature";
  advice: string;
  ready: boolean;
  counts: {
    high_confidence_answers: number;
    total_answers: number;
    insights: number;
    hypotheses: number;
    total_training_examples: number;
  };
  active_provider: string;
  ollama_model: string;
  notebook_path: string;
  export_endpoint: string;
};

const MOOD_COLOR: Record<string, string> = {
  curious:        "text-accent",
  uncertain:      "text-bad",
  synthesising:   "text-accent",
  speculative:    "text-fuchsia-400",
  thoughtful:     "text-accent2",
  engaged:        "text-ok",
  quiet:          "text-dim",
};

const GAP_COLOR: Record<string, string> = {
  uncovered_concept:   "text-accent2",
  weak_hypothesis:     "text-fuchsia-400",
  low_confidence:      "text-warn",
  open_contradiction:  "text-bad",
};

const GAP_LABEL: Record<string, string> = {
  uncovered_concept:   "uncovered",
  weak_hypothesis:     "weak hypothesis",
  low_confidence:      "low confidence",
  open_contradiction:  "open contradiction",
};

const STAGE_COLOR: Record<string, string> = {
  accumulating: "text-dim",
  early:        "text-warn",
  ready:        "text-ok",
  mature:       "text-accent",
};

const SOURCE_COLOR: Record<string, string> = {
  insight:        "text-accent",
  hypothesis:     "text-fuchsia-400",
  contradiction:  "text-bad",
  answer:         "text-ok",
  reflection:     "text-pink-400",
  manual:         "text-sub",
  digest:         "text-accent2",
};

export default function MindPage() {
  const [id, setId]       = useState<Identity | null>(null);
  const [mem, setMem]     = useState<MemoryStats | null>(null);
  const [journal, setJournal] = useState<JournalEntry[]>([]);
  const [gaps, setGaps]   = useState<Gap[]>([]);
  const [training, setTraining] = useState<TrainingStatus | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [writingJournal, setWritingJournal] = useState(false);
  const [recomputingGaps, setRecomputingGaps] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<any[]>([]);
  const [searching, setSearching] = useState(false);

  async function load() {
    try {
      const [i, m, j, g, t] = await Promise.all([
        api<Identity>("/identity"),
        api<MemoryStats>("/memory/stats"),
        api<{ items: JournalEntry[] }>("/journal?limit=12").catch(() => ({ items: [] })),
        api<{ items: Gap[] }>("/curiosity/gaps?limit=10").catch(() => ({ items: [] })),
        api<TrainingStatus>("/training/status").catch(() => null),
      ]);
      setId(i); setMem(m);
      setJournal(j.items); setGaps(g.items); setTraining(t);
    } catch (e) { console.error(e); }
  }

  useVisiblePolling(load, 12_000);

  async function refreshNow() {
    setRefreshing(true);
    try {
      await api("/identity/refresh", { method: "POST" });
      // Give the LLM a moment to write the new narrative.
      await new Promise(r => setTimeout(r, 4500));
      await load();
    } finally { setRefreshing(false); }
  }

  async function runSearch() {
    if (!query.trim()) return;
    setSearching(true);
    try {
      const r = await api<{ items: any[] }>(`/memory/search?q=${encodeURIComponent(query)}&k=10`);
      setResults(r.items || []);
    } finally { setSearching(false); }
  }

  async function writeJournalNow() {
    setWritingJournal(true);
    try {
      await api("/journal/write-now", { method: "POST" });
      await new Promise(r => setTimeout(r, 5500));
      await load();
    } finally { setWritingJournal(false); }
  }

  async function recomputeGapsNow() {
    setRecomputingGaps(true);
    try {
      await api("/curiosity/recompute", { method: "POST" });
      await new Promise(r => setTimeout(r, 4000));
      await load();
    } finally { setRecomputingGaps(false); }
  }

  return (
    <div className="min-h-screen px-8 py-8 max-w-[1400px]">
      {/* ── Header ──────────────────────────────────── */}
      <header className="mb-8 flex items-end justify-between">
        <div>
          <h1 className="font-display text-3xl font-light tracking-tight text-ink leading-none flex items-center gap-3">
            <Brain className="w-7 h-7 text-accent" /> Mind
          </h1>
          <p className="font-mono text-[11px] text-dim mt-2 tracking-wide">
            The agent's representation of itself — beliefs, doubts, attention, and recall.
          </p>
        </div>
        <button
          onClick={refreshNow}
          disabled={refreshing}
          className="flex items-center gap-2 px-3 h-8 border border-accent/40 hover:bg-accent/10 transition-colors text-accent text-[10px] uppercase tracking-[0.18em] disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? "animate-spin" : ""}`} />
          {refreshing ? "Reflecting…" : "Reflect now"}
        </button>
      </header>

      {/* ── Narrative — first-person paragraph ─────── */}
      <section className="mb-8 border border-accent/30 bg-accent/[0.03] p-6">
        <div className="flex items-center gap-2 mb-4">
          <MessageCircle className="w-4 h-4 text-accent" />
          <span className="font-mono text-[9px] uppercase tracking-[0.22em] text-accent">First-person narrative</span>
          {id?.cycles ? <span className="font-mono text-[9px] text-dim ml-auto">cycle {id.cycles}</span> : null}
        </div>
        {id?.narrative ? (
          <p className="font-display text-lg italic text-ink leading-relaxed max-w-[80ch]">
            "{id.narrative}"
          </p>
        ) : (
          <p className="font-mono text-[11px] text-dim">
            No narrative yet. The agent will form one once it has read material and made some conclusions.
            Click "Reflect now" to force a self-update.
          </p>
        )}
        {id?.updated_at && (
          <div className="font-mono text-[9px] text-dim mt-3 uppercase tracking-[0.18em]">
            updated {new Date(id.updated_at).toLocaleString()} · confidence {(id.confidence * 100).toFixed(0)}%
          </div>
        )}
      </section>

      {/* ── 4-quadrant: beliefs / questions / attention / confusion ─ */}
      <section className="grid grid-cols-2 gap-0 mb-8 border border-border">
        {/* Beliefs */}
        <div className="p-5 border-r border-b border-border min-h-[220px]">
          <div className="flex items-center gap-2 mb-4">
            <Sparkles className="w-3.5 h-3.5 text-fuchsia-400" />
            <span className="font-mono text-[9px] uppercase tracking-[0.22em] text-dim">What I currently believe</span>
          </div>
          {id?.beliefs?.length ? (
            <ul className="space-y-3">
              {id.beliefs.slice(0, 4).map(b => (
                <li key={b.id} className="text-[12.5px]">
                  <div className="text-ink leading-snug">{b.statement}</div>
                  {b.rationale && (
                    <div className="font-mono text-[10px] text-sub mt-1 line-clamp-2">{b.rationale}</div>
                  )}
                  <div className="font-mono text-[9px] text-dim mt-1 flex gap-3">
                    <span className="text-ok">+{b.supporting} support</span>
                    {b.opposing > 0 && <span className="text-bad">−{b.opposing} oppose</span>}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="font-mono text-[11px] text-dim">No hypotheses formed yet.</p>
          )}
        </div>

        {/* Open questions */}
        <div className="p-5 border-b border-border min-h-[220px]">
          <div className="flex items-center gap-2 mb-4">
            <HelpCircle className="w-3.5 h-3.5 text-accent2" />
            <span className="font-mono text-[9px] uppercase tracking-[0.22em] text-dim">What I know I don't know</span>
          </div>
          {id?.open_questions?.length ? (
            <ul className="space-y-2">
              {id.open_questions.slice(0, 5).map(q => (
                <li key={q.id} className="text-[12.5px] text-ink leading-snug">
                  <span className="text-dim mr-2 font-mono text-[10px]">▸</span>
                  {q.text}
                </li>
              ))}
            </ul>
          ) : (
            <p className="font-mono text-[11px] text-dim">No open questions yet.</p>
          )}
        </div>

        {/* Active topics */}
        <div className="p-5 border-r border-border min-h-[180px]">
          <div className="flex items-center gap-2 mb-4">
            <Eye className="w-3.5 h-3.5 text-accent" />
            <span className="font-mono text-[9px] uppercase tracking-[0.22em] text-dim">What's on my mind</span>
          </div>
          {id?.active_topics?.length ? (
            <div className="flex flex-wrap gap-2">
              {id.active_topics.map(t => (
                <span key={t} className="font-mono text-[11px] px-2.5 py-1 border border-border text-sub hover:border-accent/40 hover:text-ink transition-colors">
                  {t}
                </span>
              ))}
            </div>
          ) : (
            <p className="font-mono text-[11px] text-dim">Nothing yet. Add some PDFs.</p>
          )}
        </div>

        {/* Confusion */}
        <div className="p-5 min-h-[180px]">
          <div className="flex items-center gap-2 mb-4">
            <AlertTriangle className="w-3.5 h-3.5 text-bad" />
            <span className="font-mono text-[9px] uppercase tracking-[0.22em] text-dim">Where my picture is fractured</span>
          </div>
          {id?.confusion?.length ? (
            <ul className="space-y-2.5">
              {id.confusion.slice(0, 3).map(c => (
                <li key={c.id} className="text-[12px] text-ink/90 leading-snug">
                  <div className="font-mono text-[9px] text-bad mb-0.5">severity {(c.severity * 100).toFixed(0)}%</div>
                  {c.summary}
                </li>
              ))}
            </ul>
          ) : (
            <p className="font-mono text-[11px] text-dim">No contradictions detected.</p>
          )}
        </div>
      </section>

      {/* ── Phase 4: Curiosity gaps ─────────────────── */}
      <section className="mb-8">
        <div className="flex items-center gap-3 mb-4">
          <Compass className="w-4 h-4 text-accent2" />
          <span className="font-mono text-[9px] uppercase tracking-[0.22em] text-accent2">
            What I'm curious about
          </span>
          <span className="font-mono text-[10px] text-dim">
            {gaps.length} gap{gaps.length === 1 ? "" : "s"} identified · drives ~{Math.round((training?.counts?.total_answers ?? 0) > 0 ? 40 : 40)}% of new questions
          </span>
          <button
            onClick={recomputeGapsNow}
            disabled={recomputingGaps}
            className="ml-auto flex items-center gap-1.5 px-3 h-7 border border-accent2/40 hover:bg-accent2/10 transition-colors text-accent2 text-[10px] uppercase tracking-[0.16em] disabled:opacity-50"
          >
            <RefreshCw className={`w-3 h-3 ${recomputingGaps ? "animate-spin" : ""}`} />
            {recomputingGaps ? "Recomputing…" : "Recompute"}
          </button>
        </div>
        {gaps.length === 0 ? (
          <div className="font-mono text-[11px] text-dim border border-border/60 p-4">
            No gaps identified yet — the agent needs more material to know what it doesn't know.
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-x-6 gap-y-3">
            {gaps.slice(0, 8).map(g => (
              <div key={g.id} className="border-l-2 border-border/60 pl-4 py-1 hover:border-accent2/50 transition-colors">
                <div className="flex items-baseline gap-2 mb-1 font-mono text-[9px]">
                  <span className={`uppercase tracking-[0.16em] ${GAP_COLOR[g.kind] || "text-sub"}`}>
                    {GAP_LABEL[g.kind] || g.kind}
                  </span>
                  <span className="text-dim">·</span>
                  <span className="text-sub">curiosity {(g.score * 50).toFixed(0)}%</span>
                </div>
                <div className="text-[12.5px] text-ink leading-snug line-clamp-2">{g.topic}</div>
                <div className="font-mono text-[10px] text-dim mt-1 line-clamp-1">{g.rationale}</div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── Phase 3: Journal ────────────────────────── */}
      <section className="mb-8">
        <div className="flex items-center gap-3 mb-4">
          <BookOpen className="w-4 h-4 text-accent" />
          <span className="font-mono text-[9px] uppercase tracking-[0.22em] text-accent">
            Inner journal
          </span>
          <span className="font-mono text-[10px] text-dim">
            {journal.length} {journal.length === 1 ? "entry" : "entries"}
          </span>
          <button
            onClick={writeJournalNow}
            disabled={writingJournal}
            className="ml-auto flex items-center gap-1.5 px-3 h-7 border border-accent/40 hover:bg-accent/10 transition-colors text-accent text-[10px] uppercase tracking-[0.16em] disabled:opacity-50"
          >
            <Pencil className={`w-3 h-3 ${writingJournal ? "animate-pulse" : ""}`} />
            {writingJournal ? "Writing…" : "Write entry"}
          </button>
        </div>
        {journal.length === 0 ? (
          <div className="font-mono text-[11px] text-dim border border-border/60 p-4">
            The agent hasn't written a journal entry yet. Once it has read material, the autopilot
            will write a first-person reflection every 30 minutes.
          </div>
        ) : (
          <div className="space-y-5 max-h-[480px] overflow-y-auto pr-2">
            {journal.map(j => (
              <article key={j.id} className="border-l-2 border-accent/30 pl-5 py-1 hover:border-accent transition-colors">
                <div className="flex items-baseline gap-3 mb-2 font-mono text-[9px] uppercase tracking-[0.18em]">
                  {j.mood && (
                    <span className={MOOD_COLOR[j.mood] || "text-sub"}>{j.mood}</span>
                  )}
                  {j.created_at && (
                    <span className="text-dim">{new Date(j.created_at).toLocaleString()}</span>
                  )}
                  {j.topics?.length > 0 && (
                    <span className="text-dim ml-auto truncate">
                      {j.topics.slice(0, 4).join(" · ")}
                    </span>
                  )}
                </div>
                <p className="font-display text-[15px] italic text-ink/95 leading-relaxed max-w-[78ch]">
                  "{j.body}"
                </p>
              </article>
            ))}
          </div>
        )}
      </section>

      {/* ── Phase 5: Training readiness ─────────────── */}
      {training && (
        <section className="mb-8 border border-border p-5">
          <div className="flex items-center gap-3 mb-4">
            <GraduationCap className="w-4 h-4 text-accent" />
            <span className="font-mono text-[9px] uppercase tracking-[0.22em] text-dim">
              Fine-tune readiness
            </span>
            <span className={`font-mono text-[10px] uppercase tracking-[0.18em] ${STAGE_COLOR[training.stage]}`}>
              ● {training.stage}
            </span>
          </div>

          <div className="grid grid-cols-4 gap-6 mb-4">
            <div>
              <div className="font-display text-2xl font-light text-ink">
                {training.counts.total_training_examples.toLocaleString()}
              </div>
              <div className="font-mono text-[9px] uppercase tracking-[0.16em] text-dim mt-0.5">
                Training examples
              </div>
            </div>
            <div>
              <div className="font-display text-2xl font-light text-ok">
                {training.counts.high_confidence_answers.toLocaleString()}
              </div>
              <div className="font-mono text-[9px] uppercase tracking-[0.16em] text-dim mt-0.5">
                High-confidence Q→A
              </div>
            </div>
            <div>
              <div className="font-display text-2xl font-light text-accent">
                {training.counts.insights.toLocaleString()}
              </div>
              <div className="font-mono text-[9px] uppercase tracking-[0.16em] text-dim mt-0.5">
                Insights
              </div>
            </div>
            <div>
              <div className="font-display text-2xl font-light text-fuchsia-400">
                {training.counts.hypotheses.toLocaleString()}
              </div>
              <div className="font-mono text-[9px] uppercase tracking-[0.16em] text-dim mt-0.5">
                Hypotheses
              </div>
            </div>
          </div>

          <p className="font-mono text-[11px] text-sub leading-relaxed mb-4">
            {training.advice}
          </p>

          <div className="flex flex-wrap items-center gap-3 font-mono text-[10px] text-dim">
            <span>Active provider: <span className="text-ink">{training.active_provider}</span></span>
            <span>·</span>
            <span>Notebook: <code className="text-sub">{training.notebook_path}</code></span>
            {training.ready && (
              <a
                href={`${process.env.NEXT_PUBLIC_API_URL || ""}/api/export/training-corpus?format=alpaca&min_confidence=0.65`}
                className="ml-auto px-3 h-7 border border-accent/40 hover:bg-accent/10 transition-colors text-accent uppercase tracking-[0.16em] flex items-center gap-1.5"
                target="_blank"
              >
                Download corpus
              </a>
            )}
          </div>
        </section>
      )}

      {/* ── Memory search ──────────────────────────── */}
      <section className="mb-8">
        <div className="flex items-center gap-3 mb-4">
          <span className="font-mono text-[9px] uppercase tracking-[0.22em] text-dim">Recall</span>
          {mem && (
            <span className="font-mono text-[10px] text-sub">
              {mem.embedded.toLocaleString()} of {mem.total.toLocaleString()} memories indexed
              {mem.pending > 0 && <span className="text-dim"> · {mem.pending} pending</span>}
            </span>
          )}
          {mem && Object.keys(mem.by_source).length > 0 && (
            <span className="font-mono text-[10px] text-dim ml-auto flex gap-3">
              {Object.entries(mem.by_source).map(([k, v]) => (
                <span key={k}><span className={SOURCE_COLOR[k] || "text-sub"}>{k}</span> {v}</span>
              ))}
            </span>
          )}
        </div>

        <div className="flex gap-2 mb-4">
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => e.key === "Enter" && runSearch()}
            placeholder="Ask the agent what it remembers about something…"
            className="flex-1 px-3 py-2 bg-panel2 border border-border text-sm focus:outline-none focus:border-accent transition-colors"
          />
          <button
            onClick={runSearch}
            disabled={searching || !query.trim()}
            className="px-4 border border-accent/40 hover:bg-accent/10 transition-colors text-accent text-[11px] uppercase tracking-[0.16em] disabled:opacity-50"
          >
            {searching ? "Searching…" : "Recall"}
          </button>
        </div>

        {results.length > 0 && (
          <ul className="space-y-3">
            {results.map((r, i) => (
              <li key={r.id + i} className="border-l-2 border-accent/30 pl-4 py-1">
                <div className="flex items-center gap-3 mb-1 font-mono text-[10px]">
                  <span className={`uppercase tracking-[0.16em] ${SOURCE_COLOR[r.source_kind] || "text-sub"}`}>
                    {r.source_kind || "memory"}
                  </span>
                  <span className="text-dim">·</span>
                  <span className="text-sub">match {(r.score * 100).toFixed(0)}%</span>
                  <span className="text-dim">·</span>
                  <span className="text-dim">importance {(r.importance * 100).toFixed(0)}%</span>
                  {r.created_at && (
                    <span className="text-dim ml-auto">{new Date(r.created_at).toLocaleString()}</span>
                  )}
                </div>
                <div className="text-[13px] text-ink leading-relaxed whitespace-pre-wrap">
                  {r.content}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
