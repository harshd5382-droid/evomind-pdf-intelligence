// Rendered for unmatched routes and for any `notFound()` call. Previously the
// app had no 404 page, so bad URLs fell back to the default Next.js page that
// ignores the EvoMind shell.
import Link from "next/link";
import { Compass } from "lucide-react";

export default function NotFound() {
  return (
    <div className="px-8 py-20 flex justify-center">
      <div className="card p-8 max-w-lg w-full text-center">
        <div className="flex justify-center mb-4">
          <Compass className="w-8 h-8 text-accent" />
        </div>
        <div className="font-mono text-[9px] uppercase tracking-[0.22em] text-dim mb-2">
          404 — Not Found
        </div>
        <h1 className="font-display text-2xl font-light text-ink mb-2">
          This page doesn&apos;t exist
        </h1>
        <p className="font-mono text-[11px] text-dim leading-relaxed mb-6">
          The page you&apos;re looking for may have moved, or the link is incorrect.
        </p>
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-1.5 bg-accent text-bg font-semibold h-8 px-3.5 text-[12.5px] rounded hover:bg-accent/90 transition-colors"
        >
          Back to dashboard
        </Link>
      </div>
    </div>
  );
}
