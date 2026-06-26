"use client";

// Last-resort boundary: catches errors thrown by the root layout itself.
// It must render its own <html>/<body> because the layout failed. Styling is
// inlined since the global stylesheet / font variables may not be available.
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#030913",
          color: "#dce8f5",
          fontFamily: "monospace",
        }}
      >
        <div style={{ textAlign: "center", maxWidth: 480, padding: 24 }}>
          <h1 style={{ fontSize: 22, fontWeight: 400, marginBottom: 8 }}>
            EvoMind failed to start
          </h1>
          <p style={{ fontSize: 12, color: "#5c7696", lineHeight: 1.6, marginBottom: 24 }}>
            {error.message || "A fatal error occurred in the application shell."}
            {error.digest ? ` (ref: ${error.digest})` : ""}
          </p>
          <button
            onClick={reset}
            style={{
              background: "#c9a227",
              color: "#030913",
              border: "none",
              fontWeight: 600,
              padding: "8px 16px",
              fontSize: 13,
              cursor: "pointer",
              borderRadius: 4,
            }}
          >
            Reload
          </button>
        </div>
      </body>
    </html>
  );
}
