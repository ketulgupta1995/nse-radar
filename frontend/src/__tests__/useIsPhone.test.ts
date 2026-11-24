import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { useIsPhone } from "../lib/useIsPhone";
import { setPhone } from "./phone";

afterEach(() => {
  vi.unstubAllGlobals();
});

test("false when matchMedia is missing", () => {
  vi.stubGlobal("matchMedia", undefined);
  const { result } = renderHook(() => useIsPhone());
  expect(result.current).toBe(false);
});

test("follows the stubbed media query live", () => {
  setPhone(true);
  const { result, unmount } = renderHook(() => useIsPhone());
  expect(result.current).toBe(true);
  act(() => setPhone(false));
  expect(result.current).toBe(false);
  act(() => setPhone(true));
  expect(result.current).toBe(true);
  unmount();
});
