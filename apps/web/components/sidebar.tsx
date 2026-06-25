"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  LayoutDashboard, Activity, HelpCircle, Network,
  BookOpenText, FileText, Settings as SettingsIcon, Brain,
  Sun, Moon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";

const NAV = [
  { href: "/dashboard",  label: "Dashboard",      icon: LayoutDashboard },
  { href: "/mind",       label: "Mind",            icon: Brain           },
  { href: "/feed",       label: "Research Feed",   icon: Activity        },
  { href: "/questions",  label: "Question Tree",   icon: HelpCircle      },
  { href: "/graph",      label: "Knowledge Graph", icon: Network         },
  { href: "/memory",     label: "Memory Vault",    icon: BookOpenText    },
  { href: "/reports",    label: "Reports",         icon: FileText        },
  { href: "/settings",   label: "Settings",        icon: SettingsIcon    },
];

type ApStatus = { enabled: boolean; running: boolean };

export function Sidebar() {
  const pathname = usePathname();
  const [ap, setAp] = useState<ApStatus | null>(null);
  const [isDark, setIsDark] = useState(true);

  useEffect(() => {
    setIsDark(document.documentElement.classList.contains("dark"));
  }, []);

  function toggleTheme() {
    const next = !isDark;
    setIsDark(next);
    document.documentElement.classList.toggle("dark", next);
    localStorage.setItem("theme", next ? "dark" : "light");
  }

  useEffect(() => {
    let alive = true;
    const tick = () => api<ApStatus>("/autopilot/status").then((s) => alive && setAp(s)).catch(() => {});
    tick();
    const id = setInterval(tick, 10_000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  return (
    <aside className="w-56 shrink-0 min-h-screen flex flex-col bg-panel border-r border-border relative overflow-hidden">
      {/* Top ambient glow */}
      <div className="pointer-events-none absolute inset-x-0 top-0 h-40 bg-gradient-to-b from-accent/8 to-transparent" />

      {/* Logotype */}
      <div className="relative px-5 pt-7 pb-5">
        <div className="flex items-center gap-2.5">
          {/* Mark: concentric rotated squares */}
          <div className="relative w-7 h-7 shrink-0">
            <div className="absolute inset-0 border border-accent/50 rotate-45 rounded-[2px]" />
            <div className="absolute inset-[3px] border border-accent2/30 rounded-[1px]" />
            <div className="absolute inset-[6px] bg-accent/20 rounded-[1px]" />
          </div>
          <div>
            <div className="font-display font-semibold text-[15px] tracking-[0.08em] text-ink">
              EvoMind
            </div>
            <div className="font-mono text-[8px] tracking-[0.22em] text-dim uppercase mt-[1px]">
              PDF Intelligence
            </div>
          </div>
        </div>
        {/* Separator: gold → transparent */}
        <div className="mt-5 h-px bg-gradient-to-r from-accent/40 via-border/60 to-transparent" />
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-2 space-y-0.5">
        {NAV.map((item) => {
          const active = !!pathname?.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "group relative flex items-center gap-2.5 px-3 py-[9px] rounded text-[12.5px] font-medium transition-all duration-100",
                active ? "text-ink" : "text-sub hover:text-ink",
              )}
            >
              {/* Active indicator */}
              {active && (
                <>
                  <span className="absolute left-0 inset-y-[3px] w-[2px] bg-accent rounded-full" />
                  <span className="absolute inset-0 bg-accent/6 rounded" />
                </>
              )}
              <Icon
                className={cn(
                  "w-[15px] h-[15px] shrink-0 transition-colors duration-100",
                  active ? "text-accent" : "text-dim group-hover:text-sub",
                )}
              />
              <span className="relative">{item.label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Theme toggle */}
      <div className="px-3 pb-3">
        <button
          onClick={toggleTheme}
          className="w-full flex items-center gap-2.5 px-3 py-2 rounded text-[11px] font-mono text-dim hover:text-sub transition-colors"
          aria-label="Toggle theme"
        >
          {isDark ? <Sun className="w-3.5 h-3.5 shrink-0" /> : <Moon className="w-3.5 h-3.5 shrink-0" />}
          <span>{isDark ? "Light mode" : "Dark mode"}</span>
        </button>
      </div>

      {/* Autopilot status */}
      <div className="px-3 pb-5">
        <div className="rounded border border-border bg-panel2/80 p-3">
          <div className="flex items-center gap-2 mb-1.5">
            {ap?.running ? (
              <span className="live-dot" />
            ) : (
              <span className="inline-block w-[7px] h-[7px] rounded-full bg-dim shrink-0" />
            )}
            <span className={cn(
              "font-mono text-[9px] tracking-[0.18em] uppercase",
              ap?.running ? "text-ok" : ap?.enabled === false ? "text-dim" : "text-warn",
            )}>
              {ap?.running ? "Autopilot" : ap?.enabled === false ? "Manual" : "Autopilot · idle"}
            </span>
          </div>
          <p className="font-mono text-[10px] text-dim leading-[1.5]">
            {ap?.running
              ? "Continuously seeding, solving, and synthesising. Just upload PDFs."
              : "Continuous research loop is offline."}
          </p>
        </div>
      </div>
    </aside>
  );
}
