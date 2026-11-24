import { afterEach, expect, test, vi } from "vitest";
import { ApiError, api, browser } from "../api/client";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("400 with detail throws ApiError", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "bad" }), { status: 400 })));
  const err = await api.get("/x").catch((e: unknown) => e);
  expect(err).toBeInstanceOf(ApiError);
  expect((err as ApiError).status).toBe(400);
  expect((err as ApiError).message).toBe("bad");
});

test("success parses JSON and prefixes /api", async () => {
  const f = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
  vi.stubGlobal("fetch", f);
  expect(await api.post("/y", { a: 1 })).toEqual({ ok: true });
  expect(f.mock.calls[0][0]).toBe("/api/y");
});

const r401 = (detail: string) => new Response(JSON.stringify({ detail }), { status: 401 });

test("401 'login required' sends the browser to /login with next", async () => {
  const go = vi.spyOn(browser, "go").mockImplementation(() => undefined);
  window.history.pushState({}, "", "/stock/TCS?tab=news");
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(r401("login required")));
  const err = await api.get("/x").catch((e: unknown) => e);
  expect((err as ApiError).status).toBe(401);
  expect(go).toHaveBeenCalledWith(`/login?next=${encodeURIComponent("/stock/TCS?tab=news")}`);
});

test("other 401s and the login page itself don't redirect", async () => {
  const go = vi.spyOn(browser, "go").mockImplementation(() => undefined);
  window.history.pushState({}, "", "/login");
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(r401("login required")));
  await api.get("/x").catch(() => undefined);
  window.history.pushState({}, "", "/");
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(r401("wrong password")));
  await api.post("/login", { password: "x" }).catch(() => undefined);
  expect(go).not.toHaveBeenCalled();
});
