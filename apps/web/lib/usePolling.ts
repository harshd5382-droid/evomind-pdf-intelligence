import { useEffect, useRef } from "react";

/**
 * Poll `fn` on mount and every `intervalMs`, but SKIP ticks while the browser
 * tab is hidden (document.visibilityState !== "visible"). When the tab becomes
 * visible again we fire once immediately so the UI catches up instead of waiting
 * for the next interval boundary.
 *
 * This stops a backgrounded tab from hammering the API forever — an idle
 * dashboard/sidebar/mind view left open in another tab would otherwise keep
 * polling (and, server-side, keep the backend busy) indefinitely.
 *
 * `fn` is read through a ref, so passing a fresh closure each render does NOT
 * reset the timer; only a change to `intervalMs` does.
 */
export function useVisiblePolling(fn: () => void, intervalMs: number): void {
  const saved = useRef(fn);
  saved.current = fn;

  useEffect(() => {
    const visible = () =>
      typeof document === "undefined" || document.visibilityState === "visible";

    if (visible()) saved.current();

    const id = setInterval(() => {
      if (visible()) saved.current();
    }, intervalMs);

    const onVisibility = () => {
      if (visible()) saved.current();
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [intervalMs]);
}
