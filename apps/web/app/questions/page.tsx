"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, apiOr } from "@/lib/api";
import { pct } from "@/lib/format";
import { ChevronRight, ChevronDown, Sparkles, HelpCircle, Cpu } from "lucide-react";

type Q = {
  id: string; text: string; category: string; status: string; depth: number;
  priority: number; parent_id: string | null; document_id: string | null;
};

export default function QuestionsPage() {
  const [roots,  setRoots]  = useState<Q[]>([]);
  const [filter, setFilter] = useState<string>("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error,  setError]  = useState<string | null>(null);

  async function load() {
    const data = await apiOr<Q[]>(
      `/questions?parent_id=null&limit=200${filter ? `&status=${filter}` : ""}`,
      [],
    );
    setRoots(data);
    setLoaded(true);
  }
  useEffect(() => { load(); }, [filter]);

  return (
    <div className="px-8 py-8">
      <header className="flex items-end justify-between mb-8">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <HelpCircle className="w-5 h-5 text-accent" />
            <h1 className="font-display text-3xl font-light text-ink">Question Tree</h1>
          </div>
          <p className="font-mono text-[11px] text-dim mt-2 tracking-wide">
            Self-generated questions and their recursively expanded children.
          </p>
        </div>
        <div className="flex gap-1.5">
          {["", "open", "answered", "unresolved"].map((s) => (
            <Button
              key={s || "all"}
              size="sm"
              variant={filter === s ? "primary" : "ghost"}
              onClick={() => setFilter(s)}
            >
              {s || "all"}
            </Button>
          ))}
        </div>
      </header>

      <hr className="rule mb-6" />

      {/* Autopilot banner */}
      <div className="mb-6 flex items-center gap-3 px-4 py-2.5 border border-accent/30 bg-accent/8">
        <Cpu className="w-3.5 h-3.5 text-accent shrink-0" />
        <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-accent">
          Autopilot solving
        </span>
        <span className="live-dot" />
        <span className="font-mono text-[10px] text-sub">
          The system continuously drains open questions on its own — manual "Solve" is an optional override.
        </span>
      </div>

      <div className="font-mono text-[9px] uppercase tracking-[0.22em] text-dim mb-4">
        Root Questions — {roots.length}
      </div>

      {error && (
        <div className="mb-4 flex items-center justify-between gap-3 px-4 py-2.5 border border-bad/40 bg-bad/8">
          <span className="font-mono text-[11px] text-bad">{error}</span>
          <button
            className="font-mono text-[10px] uppercase tracking-[0.18em] text-dim hover:text-sub"
            onClick={() => setError(null)}
          >
            dismiss
          </button>
        </div>
      )}

      {loaded && roots.length === 0 ? (
        <div className="font-mono text-[11px] text-dim border border-border/50 py-8 text-center">
          No questions yet — run an autonomous cycle.
        </div>
      ) : (
        <div className="space-y-2 overflow-y-auto max-h-[calc(100vh-220px)] pr-1">
          {roots.map((q) => (
            <Node
              key={q.id}
              q={q}
              busy={busyId === q.id}
              onSolve={async () => {
                setBusyId(q.id);
                setError(null);
                try {
                  await api(`/questions/${q.id}/solve`, { method: "POST", timeoutMs: 120_000 });
                  await load();
                } catch (e) {
                  setError(e instanceof Error ? e.message : "Failed to solve question");
                } finally {
                  setBusyId(null);
                }
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function Node({ q, onSolve, busy }: { q: Q; onSolve: () => void; busy: boolean }) {
  const [open,    setOpen]    = useState(false);
  const [tree,    setTree]    = useState<any | null>(null);
  const [answers, setAnswers] = useState<any[] | null>(null);

  async function expand() {
    setOpen((o) => !o);
    if (!tree) {
      const t = await api(`/questions/${q.id}/tree`);
      setTree(t);
    }
    if (!answers) {
      const a = await api<any[]>(`/questions/${q.id}/answers`);
      setAnswers(a);
    }
  }

  return (
    <div className="border border-border bg-panel/60 hover:border-border/80 transition-colors">
      <div className="flex items-start gap-3 p-4">
        <button onClick={expand} className="mt-0.5 text-dim hover:text-sub transition-colors shrink-0">
          {open
            ? <ChevronDown className="w-3.5 h-3.5" />
            : <ChevronRight className="w-3.5 h-3.5" />}
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center flex-wrap gap-1.5 mb-2">
            <Badge variant={q.category}>{q.category}</Badge>
            <Badge variant={q.status}>{q.status}</Badge>
            <span className="font-mono text-[9px] text-dim">
              priority {q.priority.toFixed(2)}
            </span>
          </div>
          <div className="text-[13px] text-ink leading-relaxed">{q.text}</div>
        </div>
        <Button size="sm" variant="ghost" disabled={busy} onClick={onSolve} className="shrink-0">
          <Sparkles className="w-3 h-3" /> Solve
        </Button>
      </div>

      {open && (
        <div className="border-t border-border/60 px-4 pb-4 pt-3 space-y-3">
          {answers && answers.length > 0 && (
            <div className="space-y-2">
              {answers.map((a) => (
                <div key={a.id} className="border border-border/60 bg-panel p-3">
                  <div className="font-mono text-[9px] text-dim mb-2 uppercase tracking-[0.12em]">
                    confidence {pct(a.confidence)}
                  </div>
                  <div className="text-[12.5px] text-sub leading-relaxed whitespace-pre-wrap">
                    {a.text}
                  </div>
                  {a.reasoning && (
                    <div className="font-mono text-[10px] text-dim mt-2 italic border-t border-border/40 pt-2">
                      {a.reasoning}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
          {tree?.children?.length > 0 && (
            <div className="pl-4 border-l border-border/50 space-y-2 mt-2">
              {tree.children.map((c: any) => <Subtree key={c.id} node={c} />)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Subtree({ node }: { node: any }) {
  return (
    <div>
      <div className="flex items-center flex-wrap gap-1.5 text-[12.5px] py-1">
        <Badge variant={node.category}>{node.category}</Badge>
        <Badge variant={node.status}>{node.status}</Badge>
        <span className="text-sub">{node.text}</span>
      </div>
      {node.children?.length > 0 && (
        <div className="pl-4 border-l border-border/40 mt-1 space-y-1">
          {node.children.map((c: any) => <Subtree key={c.id} node={c} />)}
        </div>
      )}
    </div>
  );
}
