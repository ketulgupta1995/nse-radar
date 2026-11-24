import { cleanup, render } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import Markdown from "../components/ai/Markdown";

afterEach(cleanup);

test("HTML in the text is escaped, not run", () => {
  const { container } = render(<Markdown text={"hi <script>alert(1)</script> <img src=x onerror=y>"} />);
  expect(container.querySelector("script")).toBeNull();
  expect(container.querySelector("img")).toBeNull();
  expect(container.textContent).toContain("<script>alert(1)</script>");
});

test("headings, bullets and bold render", () => {
  const { container } = render(<Markdown text={"## Title\n- one\n- **two**\n\nplain"} />);
  expect(container.querySelector("h4")?.textContent).toBe("Title");
  expect(container.querySelectorAll("li").length).toBe(2);
  expect(container.querySelector("strong")?.textContent).toBe("two");
  expect(container.querySelector("p")?.textContent).toBe("plain");
});
