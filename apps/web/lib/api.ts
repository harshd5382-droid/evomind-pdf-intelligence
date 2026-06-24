// In dev we hit the FastAPI directly to avoid the Next.js dev-proxy
// dropping long-running POSTs (e.g. /questions/.../solve which calls the LLM).
// In production we use the same-origin /api path that next.config.mjs rewrites.
const RAW = process.env.NEXT_PUBLIC_API_URL || "";
const BASE = RAW ? `${RAW.replace(/\/$/, "")}/api` : "/api";

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

export async function api<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  const text = await res.text();
  return text ? JSON.parse(text) : (null as T);
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
  const res = await fetch(`${BASE}/upload`, { method: "POST", body: fd });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
