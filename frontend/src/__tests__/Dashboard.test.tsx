import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { setPhone } from "./phone";

import { api } from "../api/client";
import type { Dashboard as DashboardData, DashboardSince } from "../api/types";
import StatusIndicator from "../components/StatusIndicator";
import { formatDay } from "../lib/dates";
import Dashboard, { SinceStrip, sinceCount } from "../pages/Dashboard";

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const since = (over: Partial<DashboardSince> = {}): DashboardSince => ({
  last_visit_at: "2026-11-06T18:00:00+05:30", alerts: [], new_in_screens: [], positions: [], announcements: [], ...over,
});
const dash = (over: Partial<DashboardData> = {}): DashboardData => ({
  shortlist: [{ symbol: "AAA", name: "Aaa Ltd", score: 81.4, components: { rs: 90, trend: 70 },
    reasons: ["ROCE 22%"], screens: ["Uptrend leaders"], last_close: 100 }],
  alerts: [{ id: 1, kind: "k", symbol: "AAA", message: "Stop hit on AAA", link: "/positions", severity: "critical",
    dedupe_key: "d", created_at: "x", seen_at: null }],
  positions: { open: 2, invested: 200000, pnl: 5000, pnl_pct: 2.5, open_risk: 8000 },
  data: { last_trading_date: "2026-11-06", stale: false, updating: false, checks_open: 0 },
  since: null, ...over,
});

function mockApi(d: DashboardData) {
  vi.spyOn(api, "get").mockImplementation((p: string) =>
    Promise.resolve(p === "/dashboard" ? d : p === "/health" ? { ok: true } : { updating: false }),
  );
  return vi.spyOn(api, "post").mockResolvedValue({});
}
const page = () => render(<MemoryRouter><Dashboard /></MemoryRouter>);

test("formatDay", () => {
  expect(formatDay("2026-11-06")).toMatch(/Fri.*6.*Nov/);
  expect(formatDay(null)).toBe("—");
});

test("since strip is hidden when empty, and counts when not", () => {
  expect(sinceCount(since())).toBe(0);
  const { container } = render(<MemoryRouter><SinceStrip since={since()} /></MemoryRouter>);
  expect(container.firstChild).toBeNull();
  cleanup();
  render(<MemoryRouter><SinceStrip since={since({ positions: [{ symbol: "AAA", change_pct_since_visit: -3 }] })} /></MemoryRouter>);
  expect(screen.getByText("Since you were away")).toBeTruthy();
  expect(screen.getByText("1 position move")).toBeTruthy();
});

test("page shows shortlist, attention, positions and the disclaimer", async () => {
  mockApi(dash());
  page();
  expect(await screen.findByText("AAA")).toBeTruthy();
  expect(screen.getByText("ROCE 22%")).toBeTruthy();
  expect(screen.getByText("Uptrend leaders")).toBeTruthy();
  expect(screen.getByText("Stop hit on AAA")).toBeTruthy();
  expect(screen.getByText(/Ideas to research, not advice/)).toBeTruthy();
  expect(screen.getByText("Open positions")).toBeTruthy();
});

test("stale data is flagged", async () => {
  mockApi(dash({ data: { last_trading_date: "2026-10-01", stale: true, updating: false, checks_open: 2 } }));
  page();
  expect(await screen.findByText(/out of date/)).toBeTruthy();
  expect(screen.getByText(/2 price checks/)).toBeTruthy();
});

test("visit is recorded on leaving, not on load; Refresh now posts", async () => {
  const post = mockApi(dash());
  const { unmount } = page();
  await screen.findByText("AAA");
  expect(post).not.toHaveBeenCalledWith("/dashboard/visit");
  fireEvent.click(screen.getByText("Refresh now"));
  await waitFor(() => expect(post).toHaveBeenCalledWith("/jobs/refresh"));
  expect(await screen.findAllByText("Updating…")).toBeTruthy();
  unmount();
  expect(post).toHaveBeenCalledWith("/dashboard/visit");
});

test("status indicator shows progress while updating, else the data date", async () => {
  vi.spyOn(api, "get").mockResolvedValueOnce({
    updating: true, last_trading_date: "2026-11-06",
    background: { running: { job: "bhav_prices", done: 3, total: 5 }, queued: 0 }, interactive: { running: null, queued: 0 },
  });
  render(<MemoryRouter><StatusIndicator /></MemoryRouter>);
  expect(await screen.findByText(/Updating: bhav prices 3\/5…/)).toBeTruthy();
  cleanup();
  vi.spyOn(api, "get").mockResolvedValue({ updating: false, last_trading_date: "2026-11-06" });
  render(<MemoryRouter><StatusIndicator /></MemoryRouter>);
  expect(await screen.findByText(/Data as of Fri/)).toBeTruthy();
});

test("KPI strip shows portfolio value and an n/a day P&L", async () => {
  mockApi(dash());
  page();
  await screen.findByText("AAA");
  expect(screen.getByText("Portfolio value")).toBeTruthy();
  expect(screen.getByText("₹2,05,000")).toBeTruthy();
  expect(screen.getByText("n/a")).toBeTruthy();
  expect(screen.getByText("Up to date")).toBeTruthy();
});

test("KPI strip falls back to n/a for portfolio value with no open positions", async () => {
  mockApi(dash({ positions: { open: 0, invested: 0, pnl: 0, pnl_pct: 0, open_risk: 0 } }));
  page();
  await screen.findByText("AAA");
  expect(screen.getAllByText("n/a").length).toBe(1); // Day P&L only; value shows a dash
  expect(screen.getAllByText("—").length).toBeGreaterThan(0);
});

test("dismissing the since banner hides it and is remembered for that visit", () => {
  const s = since({ positions: [{ symbol: "AAA", change_pct_since_visit: -3 }] });
  const { unmount } = render(<MemoryRouter><SinceStrip since={s} /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
  expect(screen.queryByText("Since you were away")).toBeNull();
  unmount();
  render(<MemoryRouter><SinceStrip since={s} /></MemoryRouter>);
  expect(screen.queryByText("Since you were away")).toBeNull();
  cleanup();
  render(<MemoryRouter><SinceStrip since={{ ...s, last_visit_at: "2026-11-09T18:00:00+05:30" }} /></MemoryRouter>);
  expect(screen.getByText("Since you were away")).toBeTruthy();
});

// ---- Phone (N014) ----

function noWideMinWidth(html: string) {
  const widths = [...html.matchAll(/min-w-\[(\d+)px\]/g)].map((m) => Number(m[1]));
  expect(widths.filter((w) => w > 360)).toEqual([]);
}
const before = (a: Element, b: Element) => !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

test("phone: sections stack in order and Refresh is an icon button in the header", async () => {
  setPhone(true);
  const post = mockApi(dash({ since: since({ positions: [{ symbol: "AAA", change_pct_since_visit: -3 }] }) }));
  const { container } = page();
  await screen.findByText("Aaa Ltd");
  expect(screen.getByTestId("dashboard-phone")).toBeTruthy();
  const order = [
    screen.getByText("Since you were away"),
    screen.getByText(/Today's shortlist/),
    screen.getByText("Needs attention"),
    screen.getByText("My positions"),
    screen.getByText("Data freshness"),
  ];
  for (let i = 1; i < order.length; i++) expect(before(order[i - 1], order[i])).toBe(true);
  expect(screen.queryByText("Portfolio value")).toBeNull();
  const refresh = screen.getByRole("button", { name: "Refresh now" });
  expect(refresh.textContent).toBe("");
  fireEvent.click(refresh);
  await waitFor(() => expect(post).toHaveBeenCalledWith("/jobs/refresh"));
  noWideMinWidth(container.innerHTML);
});

test("phone: shortlist card shows symbol, company, score and top 2 reasons; +N more expands; tap opens the stock", async () => {
  setPhone(true);
  mockApi(dash({
    shortlist: [{ symbol: "AAA", name: "Aaa Ltd", score: 81.4, components: { rs: 90 },
      reasons: ["ROCE 22%", "Near high", "Low debt"], screens: ["Uptrend leaders"], last_close: 100 }],
  }));
  render(
    <MemoryRouter>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/stock/:sym" element={<p>stock page</p>} />
      </Routes>
    </MemoryRouter>,
  );
  const card = (await screen.findByText("Aaa Ltd")).closest("[data-testid=phone-card]") as HTMLElement;
  expect(within(card).getByText("AAA")).toBeTruthy();
  expect(within(card).getByLabelText("Score 81 out of 100")).toBeTruthy();
  expect(within(card).getByText("ROCE 22%")).toBeTruthy();
  expect(within(card).getByText("Near high")).toBeTruthy();
  expect(within(card).queryByText("Low debt")).toBeNull();
  fireEvent.click(within(card).getByText("+2 more"));
  expect(within(card).getByText("Low debt")).toBeTruthy();
  expect(within(card).getByText("Uptrend leaders")).toBeTruthy();
  expect(screen.queryByText("stock page")).toBeNull();
  fireEvent.click(card);
  expect(await screen.findByText("stock page")).toBeTruthy();
});

test("laptop keeps the KPI strip and the text Refresh button", async () => {
  setPhone(false);
  mockApi(dash());
  page();
  await screen.findByText("AAA");
  expect(screen.queryByTestId("dashboard-phone")).toBeNull();
  expect(screen.getByText("Portfolio value")).toBeTruthy();
  expect(screen.getByText("Refresh now")).toBeTruthy();
});
