"use client";

import { useEffect, useState } from "react";
import { Card, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api, apiOr } from "@/lib/api";

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

type Draft = {
  questions_per_doc: number;
  recursion_depth: number;
  autonomy_level: string;
  creativity: number;
  confidence_threshold: number;
};

export default function SettingsPage() {
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [diag, setDiag] = useState<Diagnostics | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<"idle" | "saved" | "error">("idle");

  useEffect(() => {
    apiOr<Cfg | null>("/config", null).then((c) => {
      setCfg(c);
      if (c) {
        setDraft({
          questions_per_doc: c.questions_per_doc,
          recursion_depth: c.recursion_depth,
          autonomy_level: c.autonomy_level,
          creativity: c.creativity,
          confidence_threshold: c.confidence_threshold,
        });
      }
    });
    apiOr<Diagnostics | null>("/diagnostics", null).then(setDiag);
  }, []);

  async function save() {
    if (!draft) return;
    setSaving(true);
    setStatus("idle");
    try {
      const res = await api<{ config: Cfg }>("/config", {
        method: "POST",
        body: JSON.stringify(draft),
      });
      setCfg(res.config);
      setStatus("saved");
    } catch {
      setStatus("error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="p-8 max-w-[900px] mx-auto">
      <header className="mb-6">
        <h1 className="text-3xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sub mt-1">
          Tuning knobs apply at runtime immediately. They reset on restart —
          set the matching variable in <code>.env</code> to persist.
        </p>
      </header>

      <Card>
        <CardTitle>Tuning knobs</CardTitle>
        {!draft ? (
          <div className="text-sub text-sm">Configuration unavailable.</div>
        ) : (
          <div className="space-y-4">
            <NumberField
              label="Questions per document" min={1} max={50} step={1}
              value={draft.questions_per_doc}
              onChange={(v) => setDraft({ ...draft, questions_per_doc: v })}
            />
            <NumberField
              label="Recursion depth" min={0} max={6} step={1}
              value={draft.recursion_depth}
              onChange={(v) => setDraft({ ...draft, recursion_depth: v })}
            />
            <SelectField
              label="Autonomy level"
              options={["cautious", "balanced", "aggressive"]}
              value={draft.autonomy_level}
              onChange={(v) => setDraft({ ...draft, autonomy_level: v })}
            />
            <NumberField
              label="Creativity" min={0} max={1} step={0.05}
              value={draft.creativity}
              onChange={(v) => setDraft({ ...draft, creativity: v })}
            />
            <NumberField
              label="Confidence threshold" min={0} max={1} step={0.05}
              value={draft.confidence_threshold}
              onChange={(v) => setDraft({ ...draft, confidence_threshold: v })}
            />
            <div className="flex items-center gap-3 pt-2 border-t border-border">
              <Button onClick={save} disabled={saving}>
                {saving ? "Saving…" : "Save changes"}
              </Button>
              {status === "saved" && (
                <span className="font-mono text-[11px] text-ok">Applied.</span>
              )}
              {status === "error" && (
                <span className="font-mono text-[11px] text-warn">
                  Save failed (auth may be required).
                </span>
              )}
            </div>
          </div>
        )}
      </Card>

      {cfg && (
        <Card className="mt-6">
          <CardTitle>Provider (edit in .env)</CardTitle>
          <dl className="grid grid-cols-2 gap-y-3 text-sm">
            <Row label="Primary LLM provider" value={cfg.primary_provider} />
            <Row label="Embedding provider" value={cfg.embedding_provider} />
            <Row label="Autopilot enabled" value={cfg.autopilot_enabled ? "yes" : "no"} />
          </dl>
        </Card>
      )}

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

function NumberField({
  label, value, onChange, min, max, step,
}: {
  label: string; value: number; onChange: (v: number) => void;
  min: number; max: number; step: number;
}) {
  return (
    <label className="flex items-center justify-between gap-4 text-sm">
      <span className="text-sub">{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-28 bg-bg border border-border rounded px-2 py-1 text-ink text-right focus:outline-none focus:border-accent/50"
      />
    </label>
  );
}

function SelectField({
  label, value, onChange, options,
}: {
  label: string; value: string; onChange: (v: string) => void; options: string[];
}) {
  return (
    <label className="flex items-center justify-between gap-4 text-sm">
      <span className="text-sub">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-40 bg-bg border border-border rounded px-2 py-1 text-ink focus:outline-none focus:border-accent/50"
      >
        {options.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    </label>
  );
}
