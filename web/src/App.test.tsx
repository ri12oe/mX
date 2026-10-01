// @vitest-environment jsdom
// End-to-end UI flows against a faked mX API (no network, no cost).
// The fake keeps a "session" flag that /auth/login sets, like the real cookie.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const PASSWORD = "correct horse battery";
const encoder = new TextEncoder();

interface FakeApi {
  signedIn: boolean;
  conversations: { id: string; title: string; created_at: string; updated_at: string }[];
  chat: (init: RequestInit) => Response;
  deleted: string[];
  loggedOut: boolean;
}

let api: FakeApi;

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

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

function installFakeApi(signedIn: boolean) {
  api = { signedIn, conversations: [], deleted: [], loggedOut: false, chat: () => new Response(null, { status: 500 }) };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init: RequestInit = {}) => {
      if (path === "/auth/login") {
        if (JSON.parse(String(init.body)).password !== PASSWORD) {
          return json({ detail: { code: "wrong_password", message: "Wrong password." } }, 401);
        }
        api.signedIn = true;
        return new Response(null, { status: 204 });
      }
      if (path === "/auth/logout") {
        api.signedIn = false;
        api.loggedOut = true;
        return new Response(null, { status: 204 });
      }
      if (!api.signedIn) return json({ detail: "Not signed in" }, 401);
      if (path === "/whoami") return json({ model: "claude-opus-5-5" });
      if (path.startsWith("/conversations?")) return json(api.conversations);
      if (path === "/chat") return api.chat(init);
      if (init.method === "DELETE") {
        const id = decodeURIComponent(path.split("/").pop()!);
        api.deleted.push(id);
        api.conversations = api.conversations.filter((c) => c.id !== id);
        return new Response(null, { status: 204 });
      }
      if (path.startsWith("/conversations/")) {
        return json({
          ...api.conversations[0],
          messages: [
            { id: "u1", role: "user", content: "Earlier question", image_refs: [], created_at: "" },
            { id: "a1", role: "assistant", content: "Earlier **answer**", image_refs: [], created_at: "" },
          ],
        });
      }
      return new Response(null, { status: 404 });
    }),
  );
}

function send(text: string) {
  const box = screen.getByLabelText("Message");
  fireEvent.change(box, { target: { value: text } });
  fireEvent.keyDown(box, { key: "Enter" });
}

async function renderSignedIn() {
  render(<App />);
  await waitFor(() => expect(api.signedIn && screen.queryByRole("dialog")).toBeNull());
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn(); // not implemented in jsdom
  installFakeApi(true);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("signing in", () => {
  it("shows the login screen when there's no session, then loads after signing in", async () => {
    installFakeApi(false);
    api.conversations = [{ id: "c1", title: "Loaded after sign-in", created_at: "", updated_at: new Date().toISOString() }];
    render(<App />);
    await screen.findByRole("dialog", { name: "Sign in to mX" });

    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "wrong-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByText("Wrong password.");

    fireEvent.change(screen.getByLabelText("Password"), { target: { value: PASSWORD } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByText("Loaded after sign-in");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("skips the login screen when the session cookie is still valid", async () => {
    api.conversations = [{ id: "c1", title: "Already signed in", created_at: "", updated_at: new Date().toISOString() }];
    render(<App />);
    await screen.findByText("Already signed in");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("asks to sign in again when the session ends mid-use", async () => {
    await renderSignedIn();
    api.signedIn = false; // e.g. the 30 days ran out
    send("Hello?");
    await screen.findByRole("dialog", { name: "Sign in to mX" });
    expect(screen.getByRole("alert").textContent).toContain("Your session ended");
  });

  it("signs out: calls the server, clears the chat, and shows the login screen", async () => {
    api.conversations = [{ id: "c1", title: "Private chat", created_at: "", updated_at: new Date().toISOString() }];
    render(<App />);
    await screen.findByText("Private chat");
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await screen.findByRole("dialog", { name: "Sign in to mX" });
    expect(api.loggedOut).toBe(true);
    expect(screen.queryByText("Private chat")).toBeNull();
  });
});

describe("chatting", () => {
  it("sends a message, streams the reply, shows usage, and refreshes the dial", async () => {
    api.chat = (init) => {
      expect(JSON.parse(String(init.body))).toEqual({ message: "What is 4 times 3?", mode: "normal" });
      api.conversations = [{ id: "c1", title: "What is 4 times 3?", created_at: "", updated_at: new Date().toISOString() }];
      return streamResponse([
        sse([["meta", { conversation_id: "c1", message_id: "m1" }], ["delta", { text: "The answer " }]]),
        ": ping\n\n",
        sse([["delta", { text: "is **12**." }], ["done", { usage: { model: "claude-opus-5-5", input_tokens: 500, output_tokens: 40, cost_usd: 0.0028 }, stop_reason: "end_turn" }]]),
      ]);
    };
    await renderSignedIn();
    send("What is 4 times 3?");

    await screen.findByText(/claude-opus-5-5 · 500 in \/ 40 out · \$0\.0028/);
    expect(screen.getByText("12").tagName).toBe("STRONG");
    const dial = screen.getByRole("complementary", { name: "Conversations" });
    await within(dial).findByText("What is 4 times 3?");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("What is 4 times 3?");
  });

  it("stops a reply and says nothing was saved", async () => {
    api.chat = (init) =>
      streamResponse([sse([["meta", { conversation_id: "c9", message_id: "m9" }], ["delta", { text: "Working on it" }]])], init.signal, true);
    await renderSignedIn();
    send("Long question");

    await screen.findByText("Working on it");
    fireEvent.click(screen.getByRole("button", { name: "Stop generating" }));
    await screen.findByText("Stopped. This reply wasn't saved.");
    expect(screen.getByRole("button", { name: "Send" })).toBeTruthy();
  });

  it("recovers after a failed first turn: the retry starts a new conversation", async () => {
    const bodies: { conversation_id?: string }[] = [];
    api.chat = (init) => {
      bodies.push(JSON.parse(String(init.body)));
      return bodies.length === 1
        ? streamResponse([sse([["meta", { conversation_id: "unsaved", message_id: "m1" }], ["error", { code: "provider_unavailable", message: "Lost." }]])])
        : streamResponse([sse([["meta", { conversation_id: "c2", message_id: "m2" }], ["delta", { text: "Second try works." }], ["done", { usage: { model: "m", input_tokens: 1, output_tokens: 1, cost_usd: null }, stop_reason: "end_turn" }]])]);
    };
    await renderSignedIn();
    send("First try");
    await screen.findByText(/Lost\. Nothing from this turn was saved\./);
    send("Second try");
    await screen.findByText("Second try works.");
    expect(bodies[1].conversation_id).toBeUndefined(); // not the unsaved id
  });

  it("recovers after stopping a first turn", async () => {
    const bodies: { conversation_id?: string }[] = [];
    api.chat = (init) => {
      bodies.push(JSON.parse(String(init.body)));
      return streamResponse([sse([["meta", { conversation_id: `unsaved-${bodies.length}`, message_id: "m" }], ["delta", { text: `Reply ${bodies.length}` }]])], init.signal, true);
    };
    await renderSignedIn();
    send("One");
    await screen.findByText("Reply 1");
    fireEvent.click(screen.getByRole("button", { name: "Stop generating" }));
    await screen.findByText("Stopped. This reply wasn't saved.");
    send("Two");
    await screen.findByText("Reply 2");
    expect(bodies[1].conversation_id).toBeUndefined();
  });

  it("shows a mid-stream error from the server", async () => {
    api.chat = () =>
      streamResponse([sse([["meta", { conversation_id: "c1", message_id: "m1" }], ["error", { code: "provider_unavailable", message: "Connection lost." }]])]);
    await renderSignedIn();
    send("Hi");
    await screen.findByText("Connection lost. Nothing from this turn was saved.");
  });

  it("shows an HTTP error before streaming", async () => {
    api.chat = () => json({ detail: { code: "invalid_image", message: "Image 1 is empty." } }, 422);
    await renderSignedIn();
    send("Look");
    expect(await screen.findAllByText(/Image 1 is empty\./)).not.toHaveLength(0);
    expect(screen.getByRole("alert").textContent).toContain("Image 1 is empty.");
  });

  it("opens a stored conversation and deletes it after confirming", async () => {
    api.conversations = [{ id: "c1", title: "Old chat", created_at: "", updated_at: new Date().toISOString() }];
    vi.stubGlobal("confirm", vi.fn(() => true));
    render(<App />);

    fireEvent.click(await screen.findByText("Old chat"));
    await screen.findByText("Earlier question");
    expect(screen.getByText("answer").tagName).toBe("STRONG");

    fireEvent.click(screen.getByRole("button", { name: "All chats" })); // delete lives in the history panel
    fireEvent.click(within(screen.getByRole("dialog", { name: "All chats" })).getByRole("button", { name: 'Delete "Old chat"' }));
    await screen.findByText("How can I help you learn today?");
    expect(api.deleted).toEqual(["c1"]);
    await waitFor(() => expect(screen.queryByText("Old chat")).toBeNull());
  });

  it("fills the composer from a suggestion without sending", async () => {
    await renderSignedIn();
    const fetch = globalThis.fetch as ReturnType<typeof vi.fn>;
    fireEvent.click(screen.getByRole("button", { name: /integration by parts/ }));
    expect(screen.getByLabelText("Message")).toHaveProperty("value", "Explain integration by parts with a worked example");
    expect(fetch.mock.calls.some(([path]) => path === "/chat")).toBe(false);
  });
});
