import { useCallback, useEffect, useState } from "react";

export type ThemeChoice = "light" | "dark" | "system";
const KEY = "theme";
export const DEFAULT_THEME: ThemeChoice = "dark";

export function readTheme(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    /* ignore */
  }
  return DEFAULT_THEME;
}

export function resolveTheme(choice: ThemeChoice): "light" | "dark" {
  if (choice !== "system") return choice;
  const prefersDark =
    typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
  return prefersDark ? "dark" : "light";
}

export function applyTheme(choice: ThemeChoice): void {
  const root = document.documentElement;
  const resolved = resolveTheme(choice);
  root.setAttribute("data-theme", resolved);
  root.classList.toggle("dark", resolved === "dark");
}

export function useTheme(): { theme: ThemeChoice; setTheme: (t: ThemeChoice) => void } {
  const [theme, set] = useState<ThemeChoice>(readTheme);
  useEffect(() => {
    applyTheme(theme);
    if (theme !== "system" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme("system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [theme]);
  const setTheme = useCallback((t: ThemeChoice) => {
    try {
      localStorage.setItem(KEY, t);
    } catch {
      /* ignore */
    }
    set(t);
  }, []);
  return { theme, setTheme };
}
