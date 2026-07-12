// In dev we hit the FastAPI directly to avoid the Next.js dev-proxy
// dropping long-running POSTs (e.g. /questions/.../solve which calls the LLM).
// In production we use the same-origin /api path that next.config.mjs rewrites.
const RAW = process.env.NEXT_PUBLIC_API_URL || "";
const BASE = RAW ? `${RAW.replace(/\/$/, "")}/api` : "/api";

// Optional API key for backends running with AUTH_ENABLED=true. NEXT_PUBLIC_*
// vars are inlined into the browser bundle at build time, so this key is
// visible to anyone who can load the UI — use it only for trusted/local
// deployments, and put a real authenticating proxy in front for anything else.
const API_KEY = process.env.NEXT_PUBLIC_API_KEY || "";

// Auth headers for requests that bypass `api()` (multipart uploads, etc.).
export const authHeaders = (): Record<string, string> =>
  API_KEY ? { "X-API-Key": API_KEY } : {};

export class ApiError extends Error {
  status: number;
  body: string;

  constructor(status: number, body: string) {
    super(`API ${status}: ${body}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

// Default per-request timeout so a hung backend can't freeze the tab forever.
// Callers can override (e.g. pass a longer AbortSignal) or disable with 0.
const DEFAULT_TIMEOUT_MS = 30_000;

export async function api<T = any>(
  path: string,
  init: RequestInit & { timeoutMs?: number } = {},
): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, signal: callerSignal, ...rest } = init;
  // Only arm our own timeout when the caller hasn't supplied a signal.
  const controller = !callerSignal && timeoutMs > 0 ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
  try {
    const res = await fetch(`${BASE}${path}`, {
      ...rest,
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(),
        ...(init.headers || {}),
      },
      cache: "no-store",
      signal: callerSignal ?? controller?.signal,
    });
    if (!res.ok) throw new ApiError(res.status, await res.text());
    const text = await res.text();
    return text ? JSON.parse(text) : (null as T);
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError" && controller) {
      throw new ApiError(408, `Request timed out after ${timeoutMs}ms: ${path}`);
    }
    throw e;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

export const apiUrl = (p: string) => `${BASE}${p}`;

export async function apiOr<T>(path: string, fallback: T, init: RequestInit = {}): Promise<T> {
  try {
    return await api<T>(path, init);
  } catch {
    return fallback;
  }
}

export async function safeWriteText(value: string): Promise<boolean> {
  if (typeof window === "undefined") return false;
  if (!window.isSecureContext) return false;
  if (!navigator.clipboard?.writeText) return false;
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    return false;
  }
}

export async function uploadPdf(file: File) {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`${BASE}/upload`, { method: "POST", headers: authHeaders(), body: fd });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
