import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { setPhone } from "./phone";
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

// ---- Phone (N014) ----

test("phone: card shows symbol, name, price and change; other columns behind More", async () => {
  setPhone(true);
  vi.spyOn(api, "get").mockResolvedValue([
    { symbol: "TCS", name: "Tata Consultancy", added_at: "2026-11-01T10:00:00", note: "watch results", last_close: 4000, added_close: 3800 },
  ] as never);
  const del = vi.spyOn(api, "del").mockResolvedValue({ ok: true } as never);
  const { container } = wrap();
  const card = (await screen.findByText("TCS")).closest("[data-testid=phone-card]") as HTMLElement;
  expect(within(card).getByText("Tata Consultancy")).toBeTruthy();
  expect(within(card).getByText("Last close")).toBeTruthy();
  expect(within(card).getByText("Change since added")).toBeTruthy();
  expect(within(card).queryByText("watch results")).toBeNull();
  expect(within(card).queryByText("Remove")).toBeNull();
  fireEvent.click(within(card).getByRole("button", { name: "More details for TCS" }));
  expect(within(card).getByText("watch results")).toBeTruthy();
  expect(within(card).getByText("Close when added")).toBeTruthy();
  expect([...container.innerHTML.matchAll(/min-w-\[(\d+)px\]/g)].filter((m) => Number(m[1]) > 360)).toEqual([]);
  fireEvent.click(within(card).getByText("Remove"));
  await waitFor(() => expect(del).toHaveBeenCalledWith("/watchlist/TCS"));
});
