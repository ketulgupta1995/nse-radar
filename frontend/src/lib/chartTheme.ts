import { useEffect, useState } from "react";

export interface ChartColors {
  background: string;
  text: string;
  muted: string;
  grid: string;
  up: string;
  down: string;
  accent: string;
  crosshair: string;
}

/** Used only when a CSS token is missing (e.g. in tests). Mirrors the dark and light tokens in index.css. */
const FALLBACK: Record<"light" | "dark", ChartColors> = {
  light: { background: "#ffffff", text: "#1a1d24", muted: "#626b7c", grid: "#dfe2e8", up: "#12805c", down: "#c0392b", accent: "#4f5fe0", crosshair: "#626b7c" },
  dark: { background: "#171a21", text: "#e6e9ef", muted: "#98a1b3", grid: "#2a2f3a", up: "#3fbf93", down: "#ef6b5c", accent: "#5b6cf0", crosshair: "#98a1b3" },
};

/** Reads the chart colours from the design tokens on <html>, so the chart follows the theme. */
export function chartColors(root: HTMLElement = document.documentElement): ChartColors {
  const fb = FALLBACK[root.classList.contains("dark") ? "dark" : "light"];
  const style = getComputedStyle(root);
  const t = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
  return {
    background: t("--card", fb.background),
    text: t("--foreground", fb.text),
    muted: t("--muted-foreground", fb.muted),
    grid: t("--border", fb.grid),
    up: t("--pos", fb.up),
    down: t("--neg", fb.down),
    accent: t("--accent", fb.accent),
    crosshair: t("--muted-foreground", fb.crosshair),
  };
}

/** Bumps whenever the theme changes (the `dark` class or `data-theme` on <html>), so a chart can re-theme itself live. */
export function useThemeVersion(): number {
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const obs = new MutationObserver(() => setVersion((v) => v + 1));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "data-theme"] });
    return () => obs.disconnect();
  }, []);
  return version;
}
