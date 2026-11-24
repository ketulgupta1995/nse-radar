import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { api } from "../api/client";
import AskClaude from "../components/ai/AskClaude";
import { setPhone } from "./phone";

beforeEach(() => {
  vi.spyOn(api, "get").mockResolvedValue({ available: false, detail: null } as never);
});
afterEach(() => {
  cleanup();
  act(() => setPhone(false));
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

test("phone with AI unavailable shows Copy prompt as the main button", async () => {
  act(() => setPhone(true));
  render(<AskClaude kind="stock_brief" symbol="TCS" label="Brief" />);
  expect(await screen.findByText(/paste it into claude\.ai/)).toBeTruthy();
  expect(screen.getByRole("button", { name: "Copy prompt" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Brief" })).toBeNull();
});
