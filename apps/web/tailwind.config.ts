import type { Config } from "tailwindcss";

export default {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg:       "rgb(var(--color-bg) / <alpha-value>)",
        panel:    "rgb(var(--color-panel) / <alpha-value>)",
        panel2:   "rgb(var(--color-panel2) / <alpha-value>)",
        border:   "rgb(var(--color-border) / <alpha-value>)",
        accent:   "#C9A227",
        "accent-lo": "rgba(201,162,39,0.12)",
        accent2:  "#60A5FA",
        "accent2-lo": "rgba(96,165,250,0.12)",
        ok:       "#34D399",
        warn:     "#FBBF24",
        bad:      "#FB7185",
        ink:      "rgb(var(--color-ink) / <alpha-value>)",
        sub:      "rgb(var(--color-sub) / <alpha-value>)",
        dim:      "rgb(var(--color-dim) / <alpha-value>)",
      },
      fontFamily: {
        sans:    ["var(--font-bricolage)", "system-ui", "sans-serif"],
        display: ["var(--font-spectral)", "Georgia", "serif"],
        mono:    ["var(--font-jetbrains)", "ui-monospace", "monospace"],
      },
      boxShadow: {
        soft: "0 4px 24px -8px rgba(201, 162, 39, 0.18)",
        sky:  "0 4px 24px -8px rgba(96, 165, 250, 0.15)",
        glow: "0 0 32px rgba(201, 162, 39, 0.10)",
      },
      animation: {
        "fade-up":    "fadeUp 0.45s ease-out both",
        "fade-in":    "fadeIn 0.3s ease-out both",
        "pulse-slow": "pulse 3s ease-in-out infinite",
      },
      keyframes: {
        fadeUp: {
          "0%":   { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        fadeIn: {
          "0%":   { opacity: "0" },
          "100%": { opacity: "1" },
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
