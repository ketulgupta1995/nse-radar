import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { api } from "../api/client";
import Layout from "../components/Layout";

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
