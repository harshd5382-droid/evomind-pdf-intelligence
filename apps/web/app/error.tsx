"use client";

// Route-segment error boundary. Next.js renders this whenever a route under
// the root layout throws during render. Without it the app showed a blank
// screen on any unhandled error (e.g. an API client throwing ApiError).
import { useEffect } from "react";
import { AlertTriangle, RotateCw } from "lucide-react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surfaced in the browser console for debugging; replace with a real
    // telemetry sink in Phase 4 (observability).
    console.error(error);
  }, [error]);

  return (
    <div className="px-8 py-20 flex justify-center">
      <div className="card p-8 max-w-lg w-full text-center">
        <div className="flex justify-center mb-4">
          <AlertTriangle className="w-8 h-8 text-warn" />
        </div>
        <h1 className="font-display text-2xl font-light text-ink mb-2">
          Something went wrong
        </h1>
        <p className="font-mono text-[11px] text-dim leading-relaxed mb-6">
          {error.message || "An unexpected error occurred while rendering this page."}
          {error.digest ? ` (ref: ${error.digest})` : ""}
        </p>
        <button
          onClick={reset}
          className="inline-flex items-center gap-1.5 bg-accent text-bg font-semibold h-8 px-3.5 text-[12.5px] rounded hover:bg-accent/90 transition-colors"
        >
          <RotateCw className="w-3.5 h-3.5" /> Try again
        </button>
      </div>
    </div>
  );
}
