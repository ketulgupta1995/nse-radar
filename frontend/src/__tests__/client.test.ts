import { afterEach, expect, test, vi } from "vitest";
import { ApiError, api } from "../api/client";

afterEach(() => vi.unstubAllGlobals());

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
