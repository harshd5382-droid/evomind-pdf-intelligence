"use client";

import { useEffect, useState } from "react";
import { Card, CardTitle } from "@/components/ui/card";
import { apiOr } from "@/lib/api";

type Cfg = {
  primary_provider: string;
  embedding_provider: string;
  questions_per_doc: number;
  recursion_depth: number;
  autonomy_level: string;
  creativity: number;
  confidence_threshold: number;
  autopilot_enabled: boolean;
};

type Diagnostics = {
  runtime_mode: string;
  issues: { level: string; message: string }[];
  dependencies: {
    database: { backend: string; reachable: boolean };
    feed: { mode: string };
    vector_store: { mode: string };
    graph: { mode: string; reachable?: boolean; configured?: boolean };
    queue: { mode: string };
  };
  providers: {
    primary: { name: string; configured: boolean };
    embedding: { name: string; configured: boolean };
    fallback: { name: string; configured: boolean };
    nvidia_key_pool_size: number;
  };
};

export default function SettingsPage() {
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [diag, setDiag] = useState<Diagnostics | null>(null);

  useEffect(() => {
    apiOr<Cfg | null>("/config", null).then(setCfg);
    apiOr<Diagnostics | null>("/diagnostics", null).then(setDiag);
  }, []);

  return (
    <div className="p-8 max-w-[900px] mx-auto">
      <header className="mb-6">
        <h1 className="text-3xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sub mt-1">Tunable knobs are loaded from server-side config (.env). Persist changes by editing the .env file.</p>
      </header>

      <Card>
        <CardTitle>Live configuration</CardTitle>
        {!cfg ? (
          <div className="text-sub text-sm">Configuration unavailable.</div>
        ) : (
          <dl className="grid grid-cols-2 gap-y-3 text-sm">
            <Row label="Primary LLM provider" value={cfg.primary_provider} />
            <Row label="Embedding provider" value={cfg.embedding_provider} />
            <Row label="Questions per document" value={String(cfg.questions_per_doc)} />
            <Row label="Recursion depth" value={String(cfg.recursion_depth)} />
            <Row label="Autonomy level" value={cfg.autonomy_level} />
            <Row label="Creativity" value={cfg.creativity.toFixed(2)} />
            <Row label="Confidence threshold" value={cfg.confidence_threshold.toFixed(2)} />
            <Row label="Autopilot enabled" value={cfg.autopilot_enabled ? "yes" : "no"} />
          </dl>
        )}
      </Card>

      <Card className="mt-6">
        <CardTitle>Runtime diagnostics</CardTitle>
        {!diag ? (
          <div className="text-sub text-sm">Diagnostics unavailable.</div>
        ) : (
          <dl className="grid grid-cols-2 gap-y-3 text-sm">
            <Row label="Runtime mode" value={diag.runtime_mode} />
            <Row label="Database" value={`${diag.dependencies.database.backend}${diag.dependencies.database.reachable ? "" : " (down)"}`} />
            <Row label="Feed / pubsub" value={diag.dependencies.feed.mode} />
            <Row label="Vector store" value={diag.dependencies.vector_store.mode} />
            <Row label="Graph backend" value={diag.dependencies.graph.reachable === false && diag.dependencies.graph.configured ? "sql-fallback" : diag.dependencies.graph.mode} />
            <Row label="Queue mode" value={diag.dependencies.queue.mode} />
            <Row label="Primary configured" value={diag.providers.primary.configured ? "yes" : "no"} />
            <Row label="NVIDIA key pool" value={String(diag.providers.nvidia_key_pool_size)} />
          </dl>
        )}
        {diag?.issues?.length ? (
          <div className="mt-4 pt-4 border-t border-border text-sm text-sub">
            {diag.issues.map((issue, i) => (
              <div key={`${issue.level}-${i}`}>{issue.message}</div>
            ))}
          </div>
        ) : null}
      </Card>

      <Card className="mt-6">
        <CardTitle>Switching providers</CardTitle>
        <p className="text-sm text-sub leading-relaxed">
          Set <code className="text-accent">PRIMARY_PROVIDER</code> in <code>.env</code> to one of:
          <code className="ml-2 text-accent">anthropic</code>,
          <code className="ml-2 text-accent">openai</code>,
          <code className="ml-2 text-accent">gemini</code>,
          <code className="ml-2 text-accent">ollama</code>.
          The corresponding API key (or Ollama base URL) must be set.
          Embeddings default to a local sentence-transformers model so you can run fully offline.
        </p>
      </Card>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-sub">{label}</dt>
      <dd className="text-ink">{value}</dd>
    </>
  );
}
