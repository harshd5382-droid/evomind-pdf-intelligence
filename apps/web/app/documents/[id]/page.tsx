"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { Card, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, apiOr } from "@/lib/api";
import { formatRelative } from "@/lib/utils";
import { ArrowLeft, FileText, Sparkles } from "lucide-react";

type Doc = {
  id: string; title: string; author?: string; filename: string;
  page_count: number; subject_area?: string; importance: number;
  keywords: string[]; status: string; created_at: string;
};

type Chunk = { id: string; ord: number; page: number; section: string | null; kind: string; text: string };
type Q = { id: string; text: string; category: string; status: string; priority: number; depth: number };

export default function DocumentDetail() {
  const params = useParams<{ id: string }>();
  const id = params?.id;
  const [doc, setDoc] = useState<Doc | null>(null);
  const [chunks, setChunks] = useState<{ chunks: Chunk[]; total: number } | null>(null);
  const [questions, setQuestions] = useState<Q[]>([]);
  const [offset, setOffset] = useState(0);
  const [kind, setKind] = useState<string>("");
  const [generating, setGenerating] = useState(false);
  const [missing, setMissing] = useState(false);
  const limit = 25;

  async function load() {
    if (!id) return;
    const [d, c, qs] = await Promise.all([
      apiOr<Doc | null>(`/documents/${id}`, null),
      apiOr<{ chunks: Chunk[]; total: number }>(`/documents/${id}/chunks?offset=${offset}&limit=${limit}${kind ? `&kind=${kind}` : ""}`, { chunks: [], total: 0 }),
      apiOr<Q[]>(`/documents/${id}/questions`, []),
    ]);
    setDoc(d); setChunks(c); setQuestions(qs); setMissing(!d);
  }
  useEffect(() => { load(); }, [id, offset, kind]);

  async function generateQuestions() {
    if (!id) return;
    setGenerating(true);
    try {
      await api("/analyze", { method: "POST", body: JSON.stringify({ document_id: id }) });
      await load();
    } finally {
      setGenerating(false);
    }
  }

  if (missing) return <div className="p-8 text-sub">This document is unavailable.</div>;
  if (!doc) return <div className="p-8 text-sub">Loading…</div>;

  return (
    <div className="p-8 max-w-[1300px] mx-auto space-y-6">
      <div>
        <Link href="/dashboard" className="inline-flex items-center gap-2 text-sub hover:text-ink text-sm mb-4">
          <ArrowLeft className="w-4 h-4" /> Dashboard
        </Link>
        <header className="flex items-start justify-between gap-6">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight flex items-center gap-3">
              <FileText className="w-7 h-7 text-accent" />
              {doc.title}
            </h1>
            <p className="text-sub mt-1">
              {doc.author || "Unknown author"} · {doc.page_count} pages · added {formatRelative(doc.created_at)}
            </p>
          </div>
          <Button onClick={generateQuestions} disabled={generating}>
            <Sparkles className="w-4 h-4" /> {generating ? "Generating…" : "Generate Questions"}
          </Button>
        </header>
      </div>

      <Card>
        <CardTitle>Metadata</CardTitle>
        <dl className="grid grid-cols-2 md:grid-cols-4 gap-y-3 text-sm">
          <div><dt className="text-sub text-xs uppercase tracking-wider">Subject</dt><dd>{doc.subject_area || "—"}</dd></div>
          <div><dt className="text-sub text-xs uppercase tracking-wider">Importance</dt><dd>{doc.importance.toFixed(2)}</dd></div>
          <div><dt className="text-sub text-xs uppercase tracking-wider">Status</dt><dd><Badge variant={doc.status === "ready" ? "answered" : "open"}>{doc.status}</Badge></dd></div>
          <div><dt className="text-sub text-xs uppercase tracking-wider">Filename</dt><dd className="truncate">{doc.filename}</dd></div>
        </dl>
        {doc.keywords?.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {doc.keywords.map((k) => (
              <span key={k} className="text-xs px-2 py-1 rounded-md bg-white/5 border border-border text-sub">{k}</span>
            ))}
          </div>
        )}
      </Card>

      <div className="grid lg:grid-cols-3 gap-4">
        <Card className="lg:col-span-2">
          <div className="flex items-center justify-between mb-3">
            <CardTitle className="!mb-0">Chunks ({chunks?.total ?? 0})</CardTitle>
            <div className="flex gap-1">
              {["", "text", "formula"].map((k) => (
                <Button key={k || "all"} size="sm" variant={kind === k ? "primary" : "ghost"}
                  onClick={() => { setKind(k); setOffset(0); }}>{k || "all"}</Button>
              ))}
            </div>
          </div>
          <div className="space-y-2 max-h-[640px] overflow-y-auto scrollbar pr-2">
            {chunks?.chunks.map((c) => (
              <div key={c.id} className="rounded-lg border border-border bg-panel2/50 p-3">
                <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-sub mb-1">
                  <span>p.{c.page}</span>
                  {c.section && <span>· {c.section}</span>}
                  <Badge>{c.kind}</Badge>
                  <span className="ml-auto">#{c.ord}</span>
                </div>
                <div className={c.kind === "formula" ? "font-mono text-sm text-cyan-300" : "text-sm whitespace-pre-wrap"}>
                  {c.text}
                </div>
              </div>
            ))}
          </div>
          {chunks && chunks.total > limit && (
            <div className="flex items-center justify-between pt-3 mt-3 border-t border-border text-sm">
              <Button size="sm" variant="ghost" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>Prev</Button>
              <span className="text-sub">{offset + 1}–{Math.min(offset + limit, chunks.total)} of {chunks.total}</span>
              <Button size="sm" variant="ghost" disabled={offset + limit >= chunks.total} onClick={() => setOffset(offset + limit)}>Next</Button>
            </div>
          )}
        </Card>

        <Card>
          <CardTitle>Questions about this document ({questions.length})</CardTitle>
          {questions.length === 0 ? (
            <div className="text-sub text-sm">No questions yet — click <em>Generate Questions</em>.</div>
          ) : (
            <div className="space-y-2 max-h-[640px] overflow-y-auto scrollbar pr-2">
              {questions.map((q) => (
                <div key={q.id} className="rounded-lg border border-border bg-panel2/50 p-3">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge variant={q.category}>{q.category}</Badge>
                    <Badge variant={q.status}>{q.status}</Badge>
                  </div>
                  <div className="text-sm">{q.text}</div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
