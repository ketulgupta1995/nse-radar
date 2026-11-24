import { useCallback, useState } from "react";

export type Density = "compact" | "comfortable";
const KEY = "table-density";

export function readDensity(): Density {
  try {
    return localStorage.getItem(KEY) === "comfortable" ? "comfortable" : "compact";
  } catch {
    return "compact";
  }
}

/** Table row density, shared by every table and remembered. Compact rows are 32px, comfortable 40px. */
export function useDensity(): { density: Density; setDensity: (d: Density) => void } {
  const [density, set] = useState<Density>(readDensity);
  const setDensity = useCallback((d: Density) => {
    try {
      localStorage.setItem(KEY, d);
    } catch {
      /* ignore */
    }
    set(d);
  }, []);
  return { density, setDensity };
}
