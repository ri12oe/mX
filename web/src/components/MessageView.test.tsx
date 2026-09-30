// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApiConfig } from "../api";
import type { UiMessage } from "../types";
import { MessageView } from "./MessageView";

const config: ApiConfig = { baseUrl: "http://api.test", apiKey: "k" };

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function message(patch: Partial<UiMessage>): UiMessage {
  return { id: "m", role: "assistant", content: "", images: [], imageRefs: [], ...patch };
}

describe("MessageView", () => {
  it("shows user text as plain text with attached images", () => {
    render(<MessageView config={config} message={message({ role: "user", content: "**not bold**", images: ["data:image/png;base64,AA=="] })} />);
    expect(screen.getByText("**not bold**")).toBeTruthy();
    expect(screen.getByAltText("Attached image 1")).toBeTruthy();
  });

  it("shows a thinking indicator before the first text arrives", () => {
    render(<MessageView config={config} message={message({ streaming: true })} />);
    expect(screen.getByLabelText("mX is thinking")).toBeTruthy();
  });

  it("renders markdown, math, and code, but never raw HTML", () => {
    const content = "**Answer:** $x^2$\n\n```python\nprint(1)\n```\n\n<script>alert(1)</script><b>raw</b>";
    const { container } = render(<MessageView config={config} message={message({ content })} />);
    expect(container.querySelector("strong")?.textContent).toBe("Answer:");
    expect(container.querySelector(".katex")).not.toBeNull();
    expect(container.querySelector("pre code")?.textContent).toContain("print(1)");
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
  });

  it("shows prices as text, not math", () => {
    const { container } = render(<MessageView config={config} message={message({ content: "It costs $0.05 and $1.05." })} />);
    expect(container.querySelector(".katex")).toBeNull();
    expect(container.textContent).toContain("$0.05 and $1.05");
  });

  it("shows usage, cut-off warnings, and errors", () => {
    render(
      <MessageView
        config={config}
        message={message({
          content: "Partial",
          stopReason: "max_tokens",
          error: "Stopped. This reply wasn't saved.",
          usage: { model: "claude-opus-5-5", input_tokens: 1200, output_tokens: 45, cost_usd: 0.0057 },
        })}
      />,
    );
    expect(screen.getByText(/claude-opus-5-5 · 1,200 in \/ 45 out · \$0\.0057/)).toBeTruthy();
    expect(screen.getByText(/cut off/)).toBeTruthy();
    expect(screen.getByText("Stopped. This reply wasn't saved.")).toBeTruthy();
  });

  it("says when the cost is unknown", () => {
    render(<MessageView config={config} message={message({ content: "x", usage: { model: "m", input_tokens: 1, output_tokens: 1, cost_usd: null } })} />);
    expect(screen.getByText(/cost unknown/)).toBeTruthy();
  });

  it("loads stored images with the key header, and handles failures", async () => {
    const fetch = vi.fn(async (url: string) =>
      url.endsWith("/good") ? new Response(new Blob([new Uint8Array([1])], { type: "image/png" })) : new Response(null, { status: 404 }),
    );
    vi.stubGlobal("fetch", fetch);
    render(<MessageView config={config} message={message({ role: "user", content: "look", imageRefs: ["good", "gone"] })} />);

    await waitFor(() => expect(screen.getByAltText("Attached image").getAttribute("src")).toMatch(/^blob:/));
    await screen.findByText("Image unavailable");
    const headers = (fetch.mock.calls[0] as unknown as [string, RequestInit])[1].headers;
    expect(headers).toMatchObject({ "X-mX-Key": "k" });
  });
});

describe("Markdown tables and links", () => {
  it("wraps tables for horizontal scrolling and opens links in a new tab safely", () => {
    const content = "| a | b |\n|---|---|\n| 1 | 2 |\n\nSee [docs](https://example.com).";
    const { container } = render(<MessageView config={config} message={message({ content })} />);
    expect(container.querySelector(".table-scroll > table")).not.toBeNull();
    const link = container.querySelector("a")!;
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
  });
});
