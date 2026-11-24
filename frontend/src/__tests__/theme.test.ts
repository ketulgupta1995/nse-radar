import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { applyTheme, readTheme, resolveTheme } from "../lib/theme";

function mockSystem(dark: boolean) {
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: dark && q.includes("dark"),
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

describe("theme", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.classList.remove("dark");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("defaults to dark with empty storage", () => {
    expect(readTheme()).toBe("dark");
  });

  it("a stored choice wins", () => {
    localStorage.setItem("theme", "light");
    expect(readTheme()).toBe("light");
  });

  it("system follows prefers-color-scheme", () => {
    mockSystem(true);
    expect(resolveTheme("system")).toBe("dark");
    mockSystem(false);
    expect(resolveTheme("system")).toBe("light");
  });

  it("applyTheme sets data-theme and the dark class", () => {
    applyTheme("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    applyTheme("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });
});
