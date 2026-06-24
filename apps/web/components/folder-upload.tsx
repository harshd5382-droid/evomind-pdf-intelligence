"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { apiUrl } from "@/lib/api";
import { FolderUp, Server, X, Loader2, CheckCircle2, AlertCircle } from "lucide-react";

type Result = { filename?: string; document_id: string; job_id?: string; queued?: boolean; duplicate?: boolean; original_filename?: string };
type Outcome =
  | { ok: true; count: number; new?: number; duplicates?: number; items: Result[]; scanned?: string }
  | { ok: false; error: string };

export function FolderUpload({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [tab, setTab] = useState<"folder" | "server">("folder");
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const folderRef = useRef<HTMLInputElement>(null);
  const [serverPath, setServerPath] = useState("");
  const [recursive, setRecursive] = useState(true);

  async function uploadFolder(files: FileList) {
    setBusy(true); setOutcome(null);
    try {
      const fd = new FormData();
      let n = 0;
      for (const f of Array.from(files)) {
        if (f.name.toLowerCase().endsWith(".pdf")) { fd.append("files", f, f.name); n++; }
      }
      if (n === 0) {
        setOutcome({ ok: false, error: "No PDF files found in that folder." });
        return;
      }
      const res = await fetch(apiUrl("/upload/batch"), { method: "POST", body: fd });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setOutcome({ ok: true, count: data.count, new: data.new, duplicates: data.duplicates, items: data.items });
      onDone();
    } catch (e: any) {
      setOutcome({ ok: false, error: e?.message || "Upload failed" });
    } finally {
      setBusy(false);
    }
  }

  async function ingestServerPath() {
    if (!serverPath.trim()) return;
    setBusy(true); setOutcome(null);
    try {
      const res = await fetch(apiUrl("/upload/folder"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: serverPath.trim(), recursive }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setOutcome({ ok: true, count: data.count, new: data.new, duplicates: data.duplicates, items: data.items, scanned: data.scanned });
      onDone();
    } catch (e: any) {
      setOutcome({ ok: false, error: e?.message || "Ingest failed" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="w-full max-w-2xl">
        <Card className="!p-6">
          <div className="flex items-start justify-between mb-4">
            <div>
              <h2 className="text-xl font-semibold flex items-center gap-2">
                <FolderUp className="w-5 h-5 text-accent" /> Ingest a folder of PDFs
              </h2>
              <p className="text-sub text-sm mt-1">Pick a folder or point at a server path. All PDFs found are queued for ingestion.</p>
            </div>
            <button onClick={onClose} className="text-sub hover:text-ink p-1 -mr-2"><X className="w-5 h-5" /></button>
          </div>

          <div className="flex gap-1 mb-4 border-b border-border">
            <TabBtn active={tab === "folder"} onClick={() => setTab("folder")}>Browser folder picker</TabBtn>
            <TabBtn active={tab === "server"} onClick={() => setTab("server")}>Server-side path</TabBtn>
          </div>

          {tab === "folder" ? (
            <div>
              <p className="text-sm text-sub mb-3">
                Uploads every PDF from the folder you select. Works in any browser; subfolders are included.
              </p>
              <input
                ref={folderRef} type="file" hidden multiple
                /* @ts-expect-error - non-standard but supported */
                webkitdirectory="" directory=""
                onChange={(e) => e.target.files && uploadFolder(e.target.files)}
              />
              <Button disabled={busy} onClick={() => folderRef.current?.click()}>
                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <FolderUp className="w-4 h-4" />}
                Select folder…
              </Button>
            </div>
          ) : (
            <div>
              <p className="text-sm text-sub mb-3 flex items-start gap-2">
                <Server className="w-4 h-4 mt-0.5 text-accent2" />
                <span>
                  No upload — the API server reads files directly from disk. Fast for large libraries when you run locally.
                  Path must be visible to the API process (e.g. inside the <code>./data</code> volume when using Docker).
                </span>
              </p>
              <input
                value={serverPath}
                onChange={(e) => setServerPath(e.target.value)}
                placeholder="D:\\Research\\Papers   or   /app/data/library"
                className="w-full px-3 py-2 rounded-lg bg-panel2 border border-border text-sm font-mono focus:outline-none focus:border-accent"
              />
              <label className="flex items-center gap-2 mt-3 text-sm text-sub">
                <input type="checkbox" checked={recursive} onChange={(e) => setRecursive(e.target.checked)} />
                Include subfolders
              </label>
              <div className="mt-4">
                <Button disabled={busy || !serverPath.trim()} onClick={ingestServerPath}>
                  {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Server className="w-4 h-4" />}
                  Scan & ingest
                </Button>
              </div>
            </div>
          )}

          {outcome && (
            <div className="mt-5 pt-4 border-t border-border">
              {outcome.ok ? (
                <div className="text-sm">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mb-3">
                    <span className="flex items-center gap-2 text-emerald-400">
                      <CheckCircle2 className="w-4 h-4" />
                      {(outcome.new ?? outcome.count)} queued
                    </span>
                    {(outcome.duplicates ?? 0) > 0 && (
                      <span className="flex items-center gap-1.5 text-amber-300">
                        <span className="w-1.5 h-1.5 rounded-full bg-amber-300 inline-block" />
                        {outcome.duplicates} skipped (already in library)
                      </span>
                    )}
                    {outcome.scanned && (
                      <span className="text-sub text-xs">from <code>{outcome.scanned}</code></span>
                    )}
                  </div>
                  <div className="max-h-44 overflow-y-auto scrollbar text-xs space-y-0.5 pr-2">
                    {outcome.items.slice(0, 50).map((it, i) => (
                      <div key={it.document_id + i} className="truncate flex items-center gap-2">
                        {it.duplicate ? (
                          <>
                            <span className="text-amber-400 shrink-0">⊘</span>
                            <span className="text-amber-300/80">{it.filename}</span>
                            <span className="text-dim">— already in library</span>
                          </>
                        ) : (
                          <>
                            <span className="text-emerald-400 shrink-0">+</span>
                            <span className="text-sub">{it.filename}</span>
                          </>
                        )}
                      </div>
                    ))}
                    {outcome.items.length > 50 && (
                      <div className="text-dim mt-1">… and {outcome.items.length - 50} more</div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="text-sm text-bad flex items-center gap-2">
                  <AlertCircle className="w-4 h-4" /> {outcome.error}
                </div>
              )}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

function TabBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-2 text-sm border-b-2 -mb-px transition ${
        active ? "border-accent text-ink" : "border-transparent text-sub hover:text-ink"
      }`}
    >
      {children}
    </button>
  );
}
