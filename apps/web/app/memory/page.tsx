"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { apiOr } from "@/lib/api";
import { formatRelative } from "@/lib/utils";
import { BookOpenText } from "lucide-react";

type Memo = {
  id: string; layer: string; content: string; tags: string[];
  importance: number; created_at: string;
};

export default function MemoryPage() {
  const [layer,    setLayer]    = useState<string>("");
  const [memories, setMemories] = useState<Memo[]>([]);
  const [hyps,     setHyps]     = useState<any[]>([]);

  async function load() {
    const [m, h] = await Promise.all([
      apiOr<Memo[]>(`/memory${layer ? `?layer=${layer}` : ""}`, []),
      apiOr<any[]>("/hypotheses", []),
    ]);
    setMemories(m);
    setHyps(h);
  }
  useEffect(() => { load(); }, [layer]);

  return (
    <div className="px-8 py-8 max-w-[1300px]">
      <header className="mb-8">
        <div className="flex items-center gap-3 mb-1">
          <BookOpenText className="w-5 h-5 text-accent" />
          <h1 className="font-display text-3xl font-light text-ink">Memory Vault</h1>
        </div>
        <p className="font-mono text-[11px] text-dim mt-2 tracking-wide">
          Long-term takeaways, semantic concepts, and hypotheses formed through reflection.
        </p>
      </header>

      <hr className="rule mb-6" />

      {/* Layer filter */}
      <div className="flex gap-1.5 mb-8">
        {["", "long", "semantic", "short"].map((l) => (
          <Button
            key={l || "all"}
            size="sm"
            variant={layer === l ? "primary" : "ghost"}
            onClick={() => setLayer(l)}
          >
            {l || "all layers"}
          </Button>
        ))}
      </div>

      <div className="grid lg:grid-cols-2 gap-8">
        {/* Memories */}
        <div>
          <div className="font-mono text-[9px] uppercase tracking-[0.22em] text-dim mb-4">
            Memories — {memories.length}
          </div>
          <div className="space-y-2 max-h-[600px] overflow-y-auto pr-1">
            {memories.length === 0 && (
              <div className="font-mono text-[11px] text-dim border border-border/50 py-8 text-center">
                No memories yet.
              </div>
            )}
            {memories.map((m) => (
              <div key={m.id} className="border border-border bg-panel/60 p-4 hover:border-border/80 transition-colors">
                <div className="flex items-center gap-2 mb-2">
                  <Badge>{m.layer}</Badge>
                  <span className="font-mono text-[9px] text-dim">{formatRelative(m.created_at)}</span>
                  <span className="font-mono text-[9px] text-dim ml-auto">
                    imp {m.importance.toFixed(2)}
                  </span>
                </div>
                <div className="text-[12.5px] text-sub leading-relaxed">{m.content}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Hypotheses */}
        <div>
          <div className="font-mono text-[9px] uppercase tracking-[0.22em] text-dim mb-4">
            Hypotheses — {hyps.length}
          </div>
          <div className="space-y-2 max-h-[600px] overflow-y-auto pr-1">
            {hyps.length === 0 && (
              <div className="font-mono text-[11px] text-dim border border-border/50 py-8 text-center">
                No hypotheses yet.
              </div>
            )}
            {hyps.map((h) => (
              <div key={h.id} className="border border-border bg-panel/60 p-4 hover:border-border/80 transition-colors">
                <div className="flex items-center gap-2 mb-2">
                  <span className="font-mono text-[9px] text-dim">{formatRelative(h.created_at)}</span>
                  <Badge variant={h.testable ? "answered" : "open"}>
                    {h.testable ? "testable" : "speculative"}
                  </Badge>
                </div>
                <div className="text-[13px] text-ink font-medium leading-relaxed">{h.statement}</div>
                {h.rationale && (
                  <div className="font-mono text-[10px] text-dim mt-2 italic border-t border-border/40 pt-2">
                    {h.rationale}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
