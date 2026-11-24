import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";

import { ApiError, api } from "../api/client";
import Login, { safeNext } from "../pages/Login";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function renderAt(url: string) {
  render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/stock/:symbol" element={<p>stock page</p>} />
        <Route path="/" element={<p>home page</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

function submit(password: string) {
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: "Log in" }));
}

test("submits the password and goes where the user was going", async () => {
  const post = vi.spyOn(api, "post").mockResolvedValue(null);
  renderAt(`/login?next=${encodeURIComponent("/stock/TCS")}`);
  submit("open-sesame");
  await waitFor(() => expect(screen.getByText("stock page")).toBeTruthy());
  expect(post).toHaveBeenCalledWith("/login", { password: "open-sesame" });
});

test("a wrong password shows plain error text and stays", async () => {
  vi.spyOn(api, "post").mockRejectedValue(new ApiError(401, "wrong password"));
  renderAt("/login");
  submit("nope");
  await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("not right"));
  expect(screen.queryByText("home page")).toBeNull();
});

test("next only allows same-site paths", () => {
  expect(safeNext("/jobs")).toBe("/jobs");
  expect(safeNext("//evil.example")).toBe("/");
  expect(safeNext("https://evil.example")).toBe("/");
  expect(safeNext(null)).toBe("/");
  expect(safeNext("/login")).toBe("/");
});
