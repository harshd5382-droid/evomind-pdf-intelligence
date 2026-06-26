"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { MessageSquare, Send, FileText, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

type Citation = {
  document_id: string;
  title?: string;
  page: number;
  snippet?: string;
};

type Msg = {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  confidence?: number;
};

type ChatReply = {
  conversation_id: string;
  message_id: string;
  answer: string;
  confidence: number;
  citations: Citation[];
};

const SUGGESTIONS = [
  "What are the main themes across my documents?",
  "Summarize the key findings.",
  "What contradictions exist in the corpus?",
];

export default function ChatPage() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const conversationId = useRef<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  async function send(text: string) {
    const message = text.trim();
    if (!message || busy) return;
    setError(null);
    setInput("");
    setMessages((m) => [...m, { role: "user", content: message }]);
    setBusy(true);
    try {
      const reply = await api<ChatReply>("/chat", {
        method: "POST",
        body: JSON.stringify({ message, conversation_id: conversationId.current }),
      });
      conversationId.current = reply.conversation_id;
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: reply.answer,
          citations: reply.citations,
          confidence: reply.confidence,
        },
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to reach EvoMind.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col h-screen">
      <header className="px-8 pt-8 pb-4 shrink-0">
        <div className="flex items-center gap-3 mb-1">
          <MessageSquare className="w-5 h-5 text-accent" />
          <h1 className="font-display text-3xl font-light text-ink">Ask EvoMind</h1>
        </div>
        <p className="font-mono text-[11px] text-dim mt-2 tracking-wide">
          Ask questions about your corpus. Answers are grounded in retrieved evidence, with citations.
        </p>
        <hr className="rule mt-6" />
      </header>

      {/* Conversation */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-8 pb-4">
        {messages.length === 0 ? (
          <div className="max-w-2xl mx-auto mt-12 text-center">
            <p className="font-mono text-[11px] text-dim mb-5 uppercase tracking-[0.18em]">
              Start a conversation
            </p>
            <div className="flex flex-col gap-2 items-center">
              {SUGGESTIONS.map((sug) => (
                <button
                  key={sug}
                  onClick={() => send(sug)}
                  className="text-[12.5px] text-sub border border-border bg-panel/60 px-4 py-2.5 rounded hover:border-accent/40 hover:text-ink transition-colors w-full max-w-md"
                >
                  {sug}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="max-w-3xl mx-auto space-y-5 py-4">
            {messages.map((m, i) => (
              <MessageBubble key={i} msg={m} />
            ))}
            {busy && (
              <div className="flex items-center gap-2 text-dim font-mono text-[11px]">
                <Loader2 className="w-3.5 h-3.5 animate-spin" /> EvoMind is thinking…
              </div>
            )}
          </div>
        )}
      </div>

      {/* Composer */}
      <div className="shrink-0 border-t border-border bg-panel/40 px-8 py-4">
        <div className="max-w-3xl mx-auto">
          {error && (
            <div className="mb-2 font-mono text-[10px] text-rose-300/80 border border-rose-500/20 bg-rose-500/10 px-3 py-1.5">
              {error}
            </div>
          )}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
            className="flex items-end gap-2"
          >
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send(input);
                }
              }}
              rows={1}
              placeholder="Ask anything about your documents…"
              aria-label="Message"
              className="flex-1 resize-none bg-bg border border-border rounded px-3 py-2.5 text-[13px] text-ink placeholder:text-dim focus:outline-none focus:border-accent/50 max-h-40"
            />
            <Button type="submit" disabled={busy || !input.trim()} aria-label="Send message">
              <Send className="w-3.5 h-3.5" /> Send
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}

function MessageBubble({ msg }: { msg: Msg }) {
  const isUser = msg.role === "user";
  return (
    <div className={isUser ? "flex justify-end" : "flex justify-start"}>
      <div className={isUser ? "max-w-[80%]" : "max-w-[85%] w-full"}>
        <div
          className={
            isUser
              ? "bg-accent/12 border border-accent/25 text-ink px-4 py-2.5 rounded text-[13px] leading-relaxed whitespace-pre-wrap"
              : "bg-panel border border-border text-sub px-4 py-3 rounded text-[13px] leading-relaxed whitespace-pre-wrap"
          }
        >
          {msg.content}
        </div>

        {!isUser && msg.citations && msg.citations.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {msg.citations.map((c, i) => (
              <Link
                key={`${c.document_id}-${c.page}-${i}`}
                href={`/documents/${c.document_id}`}
                title={c.snippet || ""}
                className="inline-flex items-center gap-1 px-1.5 py-px font-mono text-[9px] uppercase tracking-[0.12em] border border-border bg-panel2/60 text-dim hover:text-ink hover:border-accent/40 transition-colors"
              >
                <FileText className="w-2.5 h-2.5" />
                {(c.title || "source").slice(0, 28)} · p.{c.page}
              </Link>
            ))}
          </div>
        )}

        {!isUser && typeof msg.confidence === "number" && (
          <div className="mt-1 font-mono text-[9px] text-dim uppercase tracking-[0.12em]">
            confidence {(msg.confidence * 100).toFixed(0)}%
          </div>
        )}
      </div>
    </div>
  );
}
