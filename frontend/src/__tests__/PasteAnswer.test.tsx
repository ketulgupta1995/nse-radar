import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { ApiError, api } from "../api/client";
import AskClaude from "../components/ai/AskClaude";

beforeEach(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const status = { provider: "copy_prompt", available: true, detail: "copy the prompt", model: "sonnet", providers: [] };

function setup(post: (path: string, body?: unknown) => Promise<unknown>) {
  vi.spyOn(api, "get").mockImplementation((path: string) =>
    path === "/ai/status" ? Promise.resolve(status) : Promise.reject(new ApiError(404, "no")),
  );
  const postSpy = vi.spyOn(api, "post").mockImplementation(post as typeof api.post);
  const writeText = vi.fn(() => Promise.resolve());
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  const onDone = vi.fn();
  render(<AskClaude kind="stock_brief" symbol="AAA" label="Brief me" onDone={onDone} />);
  return { postSpy, writeText, onDone };
}

test("copy_prompt: dialog shows the prompt, copies it, and saves the pasted answer", async () => {
  const { postSpy, writeText, onDone } = setup((path) => {
    if (path === "/ai/requests")
      return Promise.resolve({ id: 7, run_id: null, status: "awaiting_answer", prompt: "PROMPT TEXT" });
    if (path === "/ai/requests/7/answer")
      return Promise.resolve({ id: 7, status: "done", response: "**Pasted** brief", error: null, run_id: null });
    return Promise.reject(new ApiError(404, "no"));
  });

  fireEvent.click(screen.getByText("Brief me"));
  const promptBox = (await screen.findByLabelText("The prompt")) as HTMLTextAreaElement;
  expect(promptBox.value).toBe("PROMPT TEXT");
  expect(screen.queryByText(/Claude is thinking/)).toBeNull();

  fireEvent.click(screen.getByText("Copy"));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith("PROMPT TEXT"));

  const open = screen.getByText("Open Claude").closest("a") as HTMLAnchorElement;
  expect(open.href).toBe("https://claude.ai/new");
  expect(open.target).toBe("_blank");

  const save = screen.getByText("Save") as HTMLButtonElement;
  expect(save.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("Paste Claude's answer"), { target: { value: "**Pasted** brief" } });
  fireEvent.click(save);

  await waitFor(() => expect(screen.queryByLabelText("The prompt")).toBeNull());
  expect(postSpy).toHaveBeenCalledWith("/ai/requests/7/answer", { text: "**Pasted** brief" });
  expect(onDone).toHaveBeenCalledWith("**Pasted** brief");
  expect(screen.getByText("Pasted").tagName).toBe("STRONG");
});

test("copy_prompt: a save error stays in the dialog", async () => {
  setup((path) => {
    if (path === "/ai/requests")
      return Promise.resolve({ id: 8, run_id: null, status: "awaiting_answer", prompt: "P" });
    return Promise.reject(new ApiError(409, "not pasted"));
  });
  fireEvent.click(screen.getByText("Brief me"));
  await screen.findByLabelText("The prompt");
  fireEvent.change(screen.getByLabelText("Paste Claude's answer"), { target: { value: "x" } });
  fireEvent.click(screen.getByText("Save"));
  expect((await screen.findByRole("alert")).textContent).toContain("not pasted");
  expect(screen.getByLabelText("The prompt")).toBeTruthy();
});
