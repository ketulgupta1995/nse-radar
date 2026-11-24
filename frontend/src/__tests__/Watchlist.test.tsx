import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { api } from "../api/client";
import Watchlist from "../pages/Watchlist";

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const wrap = () => render(<MemoryRouter><Watchlist /></MemoryRouter>);

test("shows the empty state", async () => {
  vi.spyOn(api, "get").mockResolvedValue([] as never);
  wrap();
  expect(await screen.findByText("Your watchlist is empty.")).toBeTruthy();
});

test("lists stocks and removes one", async () => {
  vi.spyOn(api, "get").mockResolvedValue([
    { symbol: "TCS", name: "Tata Consultancy", added_at: "2026-11-01T10:00:00", note: null, last_close: 4000, added_close: 3800 },
  ] as never);
  const del = vi.spyOn(api, "del").mockResolvedValue({ ok: true } as never);
  wrap();
  expect(await screen.findByText("TCS")).toBeTruthy();
  fireEvent.click(screen.getByText("Remove"));
  await waitFor(() => expect(del).toHaveBeenCalledWith("/watchlist/TCS"));
  expect(await screen.findByText("Your watchlist is empty.")).toBeTruthy();
});
