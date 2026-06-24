"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import { Card, CardTitle } from "@/components/ui/card";
import { apiOr } from "@/lib/api";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

const COLOR: Record<string, string> = {
  Paper: "#7c5cff",
  Concept: "#22d3ee",
  Hypothesis: "#f472b6",
  Insight: "#fbbf24",
  Contradiction: "#ef4444",
  Claim: "#34d399",
  Author: "#fcd34d",
  Formula: "#60a5fa",
};

const SIZE: Record<string, number> = {
  Paper: 6,
  Concept: 3,
  Insight: 5,
  Hypothesis: 4,
  Contradiction: 4,
};

export default function GraphPage() {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [data, setData] = useState<{ nodes: any[]; links: any[]; source?: string; degraded?: boolean; error?: string } | null>(null);
  const [size, setSize] = useState({ width: 1200, height: 620 });

  useEffect(() => {
    apiOr<{ nodes: any[]; links: any[]; source?: string; degraded?: boolean; error?: string }>(
      "/graph?limit=300",
      { nodes: [], links: [], source: "unavailable", degraded: true, error: "Graph data is unavailable." },
    ).then(setData);
  }, []);

  useEffect(() => {
    const node = wrapRef.current;
    if (!node) return;
    const update = () => {
      setSize({
        width: Math.max(320, node.clientWidth - 24),
        height: Math.max(420, node.clientHeight - 20),
      });
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(node);
    return () => ro.disconnect();
  }, []);

  return (
    <div className="p-8 max-w-[1400px] mx-auto">
      <header className="mb-6">
        <h1 className="text-3xl font-semibold tracking-tight">Knowledge Graph</h1>
        <p className="text-sub mt-1">Papers, concepts, hypotheses and the relationships the system has inferred.</p>
      </header>

      <div ref={wrapRef}>
      <Card className="h-[640px] !p-3 relative overflow-hidden">
        <div className="absolute top-3 left-4 flex items-center gap-3 z-10">
          <CardTitle className="!mb-0">Topology</CardTitle>
          {data && (
            <span className="text-xs text-sub">
              {data.nodes.length} nodes · {data.links.length} edges
            </span>
          )}
        </div>
        <div className="absolute top-3 right-4 z-10 flex flex-wrap gap-2">
          {data?.source && (
            <span className="text-[10px] text-sub uppercase tracking-wider mr-3">
              source {data.source}
            </span>
          )}
          {Object.entries(COLOR).slice(0, 5).map(([k, c]) => (
            <span key={k} className="text-[10px] flex items-center gap-1 text-sub uppercase tracking-wider">
              <span className="w-2 h-2 rounded-full inline-block" style={{ background: c }} />
              {k}
            </span>
          ))}
        </div>
        {data ? (
          data.nodes.length === 0 ? (
            <div className="absolute inset-0 flex items-center justify-center text-sub text-sm">
              {data.error || "No nodes yet — upload a PDF and run a cycle to populate the graph."}
            </div>
          ) : (
            <ForceGraph2D
              graphData={data}
              nodeLabel={(n: any) => `${n.label}: ${n.name}`}
              nodeColor={(n: any) => COLOR[n.label] || "#94a3b8"}
              nodeRelSize={3}
              nodeVal={(n: any) => SIZE[n.label] ?? 3}
              linkColor={() => "rgba(148,163,184,0.35)"}
              linkDirectionalArrowLength={3}
              linkDirectionalArrowRelPos={1}
              backgroundColor="#0a0a0f"
              width={size.width} height={size.height}
              cooldownTicks={120}
            />
          )
        ) : (
          <div className="text-sub text-sm pl-4 pt-4">Loading…</div>
        )}
      </Card>
      </div>
    </div>
  );
}
