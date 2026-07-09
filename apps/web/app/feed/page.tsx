"use client";

import { useEffect, useRef, useState } from "react";
import { api, apiUrl } from "@/lib/api";
import { Activity } from "lucide-react";

type Ev = { type: string; _event_id?: string; _t?: number; [k: string]: any };

// Stable identity for an event — used for both dedup and React keys.
const keyFor = (ev: Ev): string =>
  ev._event_id ||
  `${ev.type}:${ev._t || 0}:${(ev.text || ev.title || ev.statement || ev.preview || ev.summary || "").slice(0, 80)}`;

const EV_COLOR: Record<string, string> = {
  "document.ingested":     "text-accent2",
  "question.generated":    "text-violet-400",
  "answer.created":        "text-ok",
  "learner.reflected":     "text-pink-400",
  "insight.created":       "text-accent",
  "hypothesis.created":    "text-fuchsia-400",
  "contradiction.detected":"text-bad",
  "cycle.started":         "text-sub",
  "cycle.completed":       "text-sub",
  "daily.started":         "text-sub",
  "daily.completed":       "text-sub",
};

const EV_BORDER: Record<string, string> = {
  "document.ingested":     "border-l-accent2/50",
  "question.generated":    "border-l-violet-400/50",
  "answer.created":        "border-l-ok/50",
  "learner.reflected":     "border-l-pink-400/50",
  "insight.created":       "border-l-accent/50",
  "hypothesis.created":    "border-l-fuchsia-400/50",
  "contradiction.detected":"border-l-bad/50",
};

export default function FeedPage() {
  const [items, setItems] = useState<Ev[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [live, setLive] = useState<"connecting" | "live" | "reconnecting">("connecting");
  const ref = useRef<EventSource | null>(null);

  useEffect(() => {
    let mounted = true;

    // Dedup against the current (bounded) item list rather than an ever-growing
    // Set, so a long-lived stream can't leak memory.
    const mergeEvents = (incoming: Ev[]) => {
      setItems((prev) => {
        const seen = new Set(prev.map(keyFor));
        const next = [...prev];
        for (const ev of incoming) {
          const key = keyFor(ev);
          if (seen.has(key)) continue;
          seen.add(key);
          next.push(ev);
        }
        next.sort((a, b) => (b._t || 0) - (a._t || 0));
        return next.slice(0, 200);
      });
    };

    api<Ev[]>("/feed/recent?limit=50")
      .then((recent) => {
        if (!mounted) return;
        mergeEvents(recent);
      })
      .catch(() => {})
      .finally(() => {
        if (mounted) setLoaded(true);
      });

    const es = new EventSource(apiUrl("/feed/stream?backlog=0"));
    ref.current = es;
    es.onopen = () => setLive("live");
    es.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data);
        mergeEvents([{ ...ev, _t: ev._t || Date.now() }]);
      } catch {}
    };
    es.onerror = () => {
      setLive("reconnecting");
    };
    return () => {
      mounted = false;
      es.close();
    };
  }, []);

  return (
    <div className="px-8 py-8">
      {/* Header */}
      <header className="mb-8">
        <div className="flex items-center gap-3 mb-1">
          <Activity className="w-5 h-5 text-accent" />
          <h1 className="font-display text-3xl font-light text-ink">Research Feed</h1>
        </div>
        <p className="font-mono text-[11px] text-dim mt-2 tracking-wide">
          Live SSE stream — every question, answer, insight, and contradiction as it happens.
        </p>
      </header>

      <hr className="rule mb-8" />

      {/* Feed label */}
      <div className="flex items-center gap-2 mb-6">
        <span className="font-mono text-[9px] uppercase tracking-[0.22em] text-dim">Live Events</span>
        <span className={live === "live" ? "live-dot" : "inline-block w-[7px] h-[7px] rounded-full bg-dim"} />
        <span className="font-mono text-[9px] text-dim">{items.length} received</span>
        <span className="font-mono text-[9px] text-dim ml-auto">
          {live === "live" ? "stream connected" : live === "reconnecting" ? "reconnecting…" : "connecting…"}
        </span>
      </div>

      {/* Event log */}
      <div className="space-y-0 max-h-[calc(100vh-220px)] overflow-y-auto pr-2 border border-border/40">
        {!loaded && (
          <div className="font-mono text-[11px] text-dim py-8 text-center border border-border/50">
            Loading research activity…
          </div>
        )}
        {loaded && items.length === 0 && (
          <div className="font-mono text-[11px] text-dim py-8 text-center border border-border/50">
            Waiting for activity — start an autonomous cycle or upload a PDF.
          </div>
        )}
        {items.map((ev, i) => {
          const colorCls  = EV_COLOR[ev.type]  ?? "text-sub";
          const borderCls = EV_BORDER[ev.type] ?? "border-l-border";
          const text = ev.text || ev.title || ev.statement || ev.preview || ev.summary
            || JSON.stringify(ev).slice(0, 280);
          return (
            <div
              key={keyFor(ev)}
              className={`feed-row border-l-2 ${borderCls} pl-4 py-3 border-b border-border/30 animate-fade-in`}
              style={{ animationDelay: `${Math.min(i * 15, 300)}ms` }}
            >
              <div className="flex items-baseline justify-between gap-4 mb-1">
                <span className={`text-[9px] uppercase tracking-[0.15em] font-semibold ${colorCls}`}>
                  {ev.type}
                </span>
                <span className="font-mono text-[9px] text-dim shrink-0">
                  {new Date(ev._t || Date.now()).toLocaleTimeString([], {
                    hour: "2-digit", minute: "2-digit", second: "2-digit",
                  })}
                </span>
              </div>
              <div className="font-mono text-[12px] text-sub leading-[1.6]">{text}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
