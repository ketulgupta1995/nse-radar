import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { api } from "../api/client";
import Layout from "../components/Layout";
import { setPhone } from "./phone";

beforeEach(() => {
  localStorage.clear();
  // cmdk needs these browser APIs, which jsdom lacks
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Element.prototype.scrollIntoView = () => {};
  vi.spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.startsWith("/symbols/search"))
      return [{ symbol: "TCS", name: "Tata Consultancy Services", industry: "IT", in_universe: true }] as never;
    if (path.startsWith("/alerts/count")) return { unseen: 0 } as never;
    return { updating: false, last_trading_date: null, background: { running: null } } as never;
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function Stock() {
  return <div>stock page {useParams().symbol}</div>;
}

function renderShell() {
  return render(
    <MemoryRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/stock/:symbol" element={<Stock />} />
          <Route path="*" element={<div>home</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

test("sidebar shows the four groups with their links", () => {
  renderShell();
  for (const g of ["Research", "Money", "Validate", "System"]) expect(screen.getByText(g)).toBeTruthy();
  expect(screen.getByRole("link", { name: "Screener" })).toBeTruthy();
  expect(screen.getByRole("link", { name: "Track record" })).toBeTruthy();
});

test("collapse hides group headings and is remembered", () => {
  const { unmount } = renderShell();
  fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
  expect(screen.queryByText("Research")).toBeNull();
  expect(localStorage.getItem("sidebar-collapsed")).toBe("1");
  unmount();
  renderShell();
  expect(screen.queryByText("Research")).toBeNull();
  expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeTruthy();
});

test("Ctrl+K opens the palette; typing a symbol and selecting it navigates", async () => {
  renderShell();
  fireEvent.keyDown(window, { key: "k", ctrlKey: true });
  const box = await screen.findByLabelText("Find a stock or page");
  fireEvent.change(box, { target: { value: "tc" } });
  const item = await screen.findByText("Tata Consultancy Services");
  fireEvent.click(item);
  await waitFor(() => expect(screen.getByText("stock page TCS")).toBeTruthy());
});

test("laptop: sidebar present, no tab bar", () => {
  setPhone(false);
  renderShell();
  expect(screen.getByRole("navigation", { name: "Main" })).toBeTruthy();
  expect(screen.queryByRole("navigation", { name: "Tabs" })).toBeNull();
});

test("phone: no sidebar, four tabs plus More", () => {
  setPhone(true);
  renderShell();
  expect(screen.queryByRole("navigation", { name: "Main" })).toBeNull();
  const tabs = screen.getByRole("navigation", { name: "Tabs" });
  const links = within(tabs).getAllByRole("link");
  expect(links.map((l) => l.textContent)).toEqual(["Dashboard", "Screener", "Watchlist", "Portfolio"]);
  expect(within(tabs).getAllByRole("button").map((b) => b.textContent)).toEqual(["More"]);
  // home route "/" is a tab, so Dashboard is active and More is not
  expect(links[0].getAttribute("aria-current")).toBe("page");
  expect(within(tabs).getByRole("button", { name: "More" }).getAttribute("aria-current")).toBeNull();
  expect(screen.getByRole("heading", { name: "Dashboard" })).toBeTruthy();
});

test("phone: More lists the other pages; tapping one navigates and closes the sheet", async () => {
  setPhone(true);
  renderShell();
  fireEvent.click(screen.getByRole("button", { name: "More" }));
  const sheet = await screen.findByRole("dialog");
  for (const name of ["Alerts", "Backtests", "Jobs", "Sources", "Settings", "Journal", "Track record"])
    expect(within(sheet).getByRole("link", { name })).toBeTruthy();
  expect(within(sheet).queryByRole("link", { name: "Screener" })).toBeNull();
  expect(within(sheet).getByRole("button", { name: /Theme/ })).toBeTruthy();
  fireEvent.click(within(sheet).getByRole("link", { name: "Jobs" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(screen.getByRole("heading", { name: "Jobs" })).toBeTruthy();
  const tabs = screen.getByRole("navigation", { name: "Tabs" });
  expect(within(tabs).getByRole("button", { name: "More" }).getAttribute("aria-current")).toBe("page");
});

test("phone: the search button opens the palette", async () => {
  setPhone(true);
  renderShell();
  fireEvent.click(screen.getByRole("button", { name: "Search stocks and pages" }));
  const box = await screen.findByLabelText("Find a stock or page");
  await waitFor(() => expect(document.activeElement).toBe(box));
  expect(screen.getByRole("button", { name: "Close search" })).toBeTruthy();
});

test("switching to a phone width swaps the shell live", () => {
  setPhone(false);
  renderShell();
  expect(screen.getByRole("navigation", { name: "Main" })).toBeTruthy();
  act(() => setPhone(true));
  expect(screen.queryByRole("navigation", { name: "Main" })).toBeNull();
  expect(screen.getByRole("navigation", { name: "Tabs" })).toBeTruthy();
});
