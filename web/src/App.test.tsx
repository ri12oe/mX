// @vitest-environment jsdom
// End-to-end UI flows against a faked mX API (no network, no cost).
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const CONFIG = { baseUrl: "http://api.test", apiKey: "test-key" };
const encoder = new TextEncoder();

interface Api {
  conversations: { id: string; title: string; created_at: string; updated_at: string }[];
  chat: (init: RequestInit) => Response;
  deleted: string[];
}

function sse(events: [string, object][]): string {
  return events.map(([name, data]) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join("");
}

function streamResponse(chunks: string[], signal?: AbortSignal | null, keepOpen = false): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      if (!keepOpen) controller.close();
      signal?.addEventListener("abort", () => controller.error(new DOMException("aborted", "AbortError")));
    },
  });
  return new Response(body, { headers: { "Content-Type": "text/event-stream" } });
}

let api: Api;

function installFakeApi() {
  api = { conversations: [], deleted: [], chat: () => new Response(null, { status: 500 }) };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const path = url.replace(CONFIG.baseUrl, "");
      if ((init.headers as Record<string, string>)["X-mX-Key"] !== CONFIG.apiKey) {
        return new Response(JSON.stringify({ detail: "Invalid or missing X-mX-Key" }), { status: 401 });
      }
      if (path === "/whoami") return new Response(JSON.stringify({ model: "claude-opus-5-5" }));
      if (path.startsWith("/conversations?")) return new Response(JSON.stringify(api.conversations));
      if (path === "/chat") return api.chat(init);
      if (init.method === "DELETE") {
        const id = decodeURIComponent(path.split("/").pop()!);
        api.deleted.push(id);
        api.conversations = api.conversations.filter((c) => c.id !== id);
        return new Response(null, { status: 204 });
      }
      if (path.startsWith("/conversations/")) {
        return new Response(JSON.stringify({
          ...api.conversations[0],
          messages: [
            { id: "u1", role: "user", content: "Earlier question", image_refs: [], created_at: "" },
            { id: "a1", role: "assistant", content: "Earlier **answer**", image_refs: [], created_at: "" },
          ],
        }));
      }
      return new Response(null, { status: 404 });
    }),
  );
}

function storage(config: object | null) {
  const data = new Map<string, string>(config ? [["mx.config", JSON.stringify(config)]] : []);
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
  });
}

function send(text: string) {
  const box = screen.getByLabelText("Message");
  fireEvent.change(box, { target: { value: text } });
  fireEvent.keyDown(box, { key: "Enter" });
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn(); // not implemented in jsdom
  installFakeApi();
  storage(CONFIG);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("asks for a key on first run", () => {
    storage(null);
    render(<App />);
    expect(screen.getByRole("dialog", { name: "Connect to mX" })).toBeTruthy();
  });

  it("sends a message, streams the reply, shows usage, and refreshes the sidebar", async () => {
    api.chat = (init) => {
      expect(JSON.parse(String(init.body))).toEqual({ message: "What is 4 times 3?", mode: "normal" });
      api.conversations = [{ id: "c1", title: "What is 4 times 3?", created_at: "", updated_at: new Date().toISOString() }];
      return streamResponse([
        sse([["meta", { conversation_id: "c1", message_id: "m1" }], ["delta", { text: "The answer " }]]),
        sse([["delta", { text: "is **12**." }], ["done", { usage: { model: "claude-opus-5-5", input_tokens: 500, output_tokens: 40, cost_usd: 0.0028 }, stop_reason: "end_turn" }]]),
      ]);
    };
    render(<App />);
    send("What is 4 times 3?");

    await screen.findByText(/claude-opus-5-5 · 500 in \/ 40 out · \$0\.0028/);
    expect(screen.getByText("12").tagName).toBe("STRONG");
    const sidebar = screen.getByRole("complementary", { name: "Conversations" });
    await within(sidebar).findByText("What is 4 times 3?");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("What is 4 times 3?");
  });

  it("stops a reply and says nothing was saved", async () => {
    api.chat = (init) =>
      streamResponse([sse([["meta", { conversation_id: "c9", message_id: "m9" }], ["delta", { text: "Working on it" }]])], init.signal, true);
    render(<App />);
    send("Long question");

    await screen.findByText("Working on it");
    fireEvent.click(screen.getByRole("button", { name: "Stop generating" }));
    await screen.findByText("Stopped. This reply wasn't saved.");
    expect(screen.getByRole("button", { name: "Send" })).toBeTruthy();
  });

  it("shows a mid-stream error from the server", async () => {
    api.chat = () =>
      streamResponse([sse([["meta", { conversation_id: "c1", message_id: "m1" }], ["error", { code: "provider_unavailable", message: "Connection lost." }]])]);
    render(<App />);
    send("Hi");
    await screen.findByText("Connection lost. Nothing from this turn was saved.");
  });

  it("shows an HTTP error before streaming", async () => {
    api.chat = () => new Response(JSON.stringify({ detail: { code: "invalid_image", message: "Image 1 is empty." } }), { status: 422 });
    render(<App />);
    send("Look");
    expect(await screen.findAllByText(/Image 1 is empty\./)).not.toHaveLength(0);
    expect(screen.getByRole("alert").textContent).toContain("Image 1 is empty.");
  });

  it("reopens the key dialog when the key is rejected", async () => {
    storage({ ...CONFIG, apiKey: "stale-key" });
    render(<App />);
    await screen.findByRole("dialog", { name: "Connect to mX" });
    expect(screen.getByRole("alert").textContent).toContain("Your API key was rejected");
  });

  it("opens a stored conversation and deletes it after confirming", async () => {
    api.conversations = [{ id: "c1", title: "Old chat", created_at: "", updated_at: new Date().toISOString() }];
    vi.stubGlobal("confirm", vi.fn(() => true));
    render(<App />);

    fireEvent.click(await screen.findByText("Old chat"));
    await screen.findByText("Earlier question");
    expect(screen.getByText("answer").tagName).toBe("STRONG");

    fireEvent.click(screen.getByRole("button", { name: 'Delete "Old chat"' }));
    await screen.findByText("How can I help you learn today?");
    expect(api.deleted).toEqual(["c1"]);
    await waitFor(() => expect(screen.queryByText("Old chat")).toBeNull());
  });

  it("fills the composer from a suggestion without sending", () => {
    const fetch = globalThis.fetch as ReturnType<typeof vi.fn>;
    render(<App />);
    const callsBefore = fetch.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: /integration by parts/ }));
    expect(screen.getByLabelText("Message")).toHaveProperty("value", "Explain integration by parts with a worked example");
    expect(fetch.mock.calls.length).toBe(callsBefore);
  });
});

describe("App first run", () => {
  it("connects with a key, saves it, and loads conversations", async () => {
    storage(null);
    api.conversations = [{ id: "c1", title: "Loaded after connecting", created_at: "", updated_at: new Date().toISOString() }];
    render(<App />);
    fireEvent.change(screen.getByLabelText("API address"), { target: { value: CONFIG.baseUrl } });
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: CONFIG.apiKey } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    await screen.findByText("Loaded after connecting");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(JSON.parse(localStorage.getItem("mx.config")!)).toEqual(CONFIG);
  });
});
