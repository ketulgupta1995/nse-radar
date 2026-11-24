import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import type { Announcement } from "../api/types";
import Announcements, { bodyLead, categoryLabel, displayTitle } from "../components/stock/Announcements";
import NewsList, { newsTime } from "../components/stock/NewsList";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const CATS = [
  { category: "results", alert: true },
  { category: "pledge", alert: true, severity: "warn" },
  { category: "routine", alert: false, hidden: true },
  { category: "other_important", alert: true },
];
const ann = (over: Partial<Announcement>): Announcement => ({
  id: 1, source: "nse_api", symbol: "TCS", ts: "2026-11-04T11:00:07+05:30", category: "other",
  headline: "Updates", body: null, url: null, ...over,
});

let urls: string[];
function stub(rows: Announcement[] | ((url: string) => Announcement[])) {
  urls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    urls.push(url);
    if (url === "/api/news/categories") return new Response(JSON.stringify(CATS), { status: 200 });
    const list = typeof rows === "function" ? rows(url) : rows;
    return new Response(JSON.stringify(list), { status: 200 });
  }));
}

test("body lead drops NSE's boilerplate and long text is cut", () => {
  expect(bodyLead("Tata Consultancy Services Limited has informed the Exchange regarding 'Press Release - TCS Study'."))
    .toBe("Press Release - TCS Study");
  expect(bodyLead("X Ltd has informed the Exchange about Schedule of meet")).toBe("Schedule of meet");
  expect(bodyLead("y".repeat(300)).length).toBe(140);
  expect(bodyLead(null)).toBe("");
  expect(categoryLabel("order_win")).toBe("Order win");
  expect(categoryLabel("something_new")).toBe("Something new");
});

test("title prefers the body's sentence and keeps NSE's subject as a hint", () => {
  const a = ann({ body: "TCS has informed the Exchange regarding 'Press Release - Big news'" });
  expect(displayTitle(a)).toEqual({ title: "Press Release - Big news", subject: "Updates" });
  expect(displayTitle(ann({ headline: "Credit rating" }))).toEqual({ title: "Credit rating", subject: null });
});

test("rows show date, category chip (pledge amber), expandable body and a safe PDF link", async () => {
  stub([
    ann({ id: 1, category: "pledge", headline: "Pledge", body: "Promoter pledged shares", url: "https://x.test/a.pdf" }),
    ann({ id: 2, category: "results", headline: "Results", body: null, url: null }),
  ]);
  const { container } = render(<Announcements symbol="TCS" />);
  expect(await screen.findByText("Promoter pledged shares", { selector: "strong" })).toBeTruthy();
  expect(container.querySelector('[data-category="pledge"]')?.className).toContain("amber");
  expect(container.querySelector('[data-category="results"]')?.className).not.toContain("amber");
  expect(container.querySelectorAll("details")).toHaveLength(1);
  const pdf = screen.getByText("PDF") as HTMLAnchorElement;
  expect(pdf.target).toBe("_blank");
  expect(pdf.rel).toContain("noopener");
  expect(screen.getAllByText("4 Nov").length).toBe(2);
});

test("category chips filter on the server; routine filings are off until toggled", async () => {
  stub([ann({})]);
  render(<Announcements symbol="TCS" />);
  await screen.findByText("Updates");
  expect(urls.at(-1)).toContain("symbol=TCS");
  expect(urls.at(-1)).toContain("include_hidden=0");
  expect(screen.queryByRole("button", { name: "Routine" })).toBeNull(); // hidden category has no chip
  expect(screen.getByRole("button", { name: "Other" })).toBeTruthy();
  const pledge = await screen.findByRole("button", { name: "Pledge" });
  fireEvent.click(pledge);
  await waitFor(() => expect(urls.at(-1)).toContain("category=pledge"));
  expect(pledge.getAttribute("aria-pressed")).toBe("true");
  fireEvent.click(pledge);
  await waitFor(() => expect(urls.at(-1)).not.toContain("category="));
  fireEvent.click(screen.getByLabelText("Show routine filings"));
  await waitFor(() => expect(urls.at(-1)).toContain("include_hidden=1"));
});

test("empty announcements message", async () => {
  stub([]);
  render(<Announcements symbol="TCS" />);
  expect(await screen.findByText(/No announcements/)).toBeTruthy();
});

test("news list: external links with feed name and time", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([
    { id: 1, source: "rss", feed: "ET Markets", ts: "2026-11-09T18:41:00+05:30", title: "TCS wins a deal",
      url: "https://e.test/1", summary: null, symbols: ["TCS"] },
  ]), { status: 200 })));
  render(<NewsList symbol="TCS" />);
  const link = (await screen.findByText("TCS wins a deal")) as HTMLAnchorElement;
  expect(link.href).toBe("https://e.test/1");
  expect(link.target).toBe("_blank");
  expect(screen.getByText(/ET Markets · 9 Nov, 18:41/)).toBeTruthy();
  expect(newsTime("2026-11-09T09:05:00+05:30")).toBe("9 Nov, 09:05");
});

test("news list empty state", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200 })));
  render(<NewsList symbol="TCS" />);
  expect(await screen.findByText("No news mentions this stock yet.")).toBeTruthy();
});
