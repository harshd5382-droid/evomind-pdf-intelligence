import { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const STYLES: Record<string, string> = {
  understanding: "bg-blue-500/10 text-blue-300/80 border-blue-500/20",
  deep_logic:    "bg-violet-500/10 text-violet-300/80 border-violet-500/20",
  missing_data:  "bg-amber-500/10 text-amber-300/80 border-amber-500/20",
  contradiction: "bg-rose-500/10 text-rose-300/80 border-rose-500/20",
  math:          "bg-cyan-500/10 text-cyan-300/80 border-cyan-500/20",
  application:   "bg-emerald-500/10 text-emerald-300/80 border-emerald-500/20",
  research:      "bg-fuchsia-500/10 text-fuchsia-300/80 border-fuchsia-500/20",
  meta:          "bg-pink-500/10 text-pink-300/80 border-pink-500/20",
  improvement:   "bg-indigo-500/10 text-indigo-300/80 border-indigo-500/20",
  open:          "bg-amber-500/10 text-amber-300/80 border-amber-500/20",
  answered:      "bg-emerald-500/10 text-emerald-300/80 border-emerald-500/20",
  unresolved:    "bg-rose-500/10 text-rose-300/80 border-rose-500/20",
  default:       "bg-white/5 text-sub border-border",
};

export function Badge({
  variant = "default",
  className,
  ...props
}: HTMLAttributes<HTMLSpanElement> & { variant?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-1.5 py-px font-mono text-[9px] uppercase tracking-[0.15em] border",
        STYLES[variant] ?? STYLES.default,
        className,
      )}
      {...props}
    />
  );
}
