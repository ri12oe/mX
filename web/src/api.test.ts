import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  deleteConversation,
  getConversation,
  imageUrl,
  isSignedOut,
  listConversations,
  login,
  logout,
  streamChat,
  whoami,
} from "./api";
import type { ChatEvent } from "./types";

function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

function mockFetch(response: Response | Error) {
  const fn = vi.fn(async (_url: string, _init?: RequestInit) => {
    if (response instanceof Error) throw response;
    return response;
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("streamChat", () => {
  it("posts same-origin with the session cookie and emits typed events", async () => {
    const fetch = mockFetch(
      sseResponse([
        'event: meta\ndata: {"conversation_id": "c1", "message_id": "m1"}\n\nevent: delta\ndata: {"text": "The answer ',
        'is 12."}\n\n: ping\n\nevent: done\ndata: {"usage": {"model": "claude-opus-5-5", "input_tokens": 5, "output_tokens": 3, "cost_usd": 0.0001}, "stop_reason": "end_turn"}\n\n',
      ]),
    );
    const events: ChatEvent[] = [];
    await streamChat({ message: "4 x 3?", mode: "brief" }, (e) => events.push(e));

    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe("/chat");
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("same-origin");
    expect(init?.headers).toEqual({ "Content-Type": "application/json" }); // no key in the browser
    expect(JSON.parse(String(init?.body))).toEqual({ message: "4 x 3?", mode: "brief" });

    expect(events.map((e) => e.type)).toEqual(["meta", "delta", "done"]); // heartbeat skipped
    expect(events[1]).toEqual({ type: "delta", text: "The answer is 12." });
  });

  it("passes mid-stream error events through", async () => {
    mockFetch(sseResponse(['event: meta\ndata: {"conversation_id": "c", "message_id": "m"}\n\n',
      'event: error\ndata: {"code": "provider_unavailable", "message": "lost"}\n\n']));
    const events: ChatEvent[] = [];
    await streamChat({ message: "hi", mode: "normal" }, (e) => events.push(e));
    expect(events[1]).toEqual({ type: "error", code: "provider_unavailable", message: "lost" });
  });

  it("turns an HTTP error with {code, message} into ApiError", async () => {
    mockFetch(new Response(JSON.stringify({ detail: { code: "invalid_image", message: "Image 1 is empty." } }), { status: 422 }));
    await expect(streamChat({ message: "hi", mode: "normal" }, () => {})).rejects.toMatchObject({
      name: "ApiError", status: 422, code: "invalid_image", message: "Image 1 is empty.",
    });
  });

  it("errors clearly when a chat response has no body", async () => {
    mockFetch(new Response(null, { status: 200 }));
    await expect(streamChat({ message: "hi", mode: "normal" }, () => {})).rejects.toMatchObject({ code: "no_stream" });
  });
});

describe("sign-in", () => {
  it("login posts the password; logout posts to /auth/logout", async () => {
    const fetch = mockFetch(new Response(null, { status: 204 }));
    await login("hunter2-hunter2");
    await logout();
    expect(fetch.mock.calls[0][0]).toBe("/auth/login");
    expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual({ password: "hunter2-hunter2" });
    expect(fetch.mock.calls[1][0]).toBe("/auth/logout");
    expect(fetch.mock.calls[1][1]?.method).toBe("POST");
  });

  it("a wrong password is an ApiError with the server's message", async () => {
    mockFetch(new Response(JSON.stringify({ detail: { code: "wrong_password", message: "Wrong password." } }), { status: 401 }));
    await expect(login("nope")).rejects.toMatchObject({ status: 401, message: "Wrong password." });
  });

  it("whoami tells signed-out apart from other failures", async () => {
    mockFetch(new Response(JSON.stringify({ detail: "Not signed in" }), { status: 401 }));
    expect(isSignedOut(await whoami().catch((e: unknown) => e))).toBe(true);
    mockFetch(new Response("oops", { status: 500 }));
    expect(isSignedOut(await whoami().catch((e: unknown) => e))).toBe(false);
    expect(isSignedOut(new Error("x"))).toBe(false);
  });
});

describe("other calls", () => {
  it("reads conversations and escapes ids in paths", async () => {
    const fetch = mockFetch(new Response(JSON.stringify({ id: "a/b", messages: [] })));
    expect((await getConversation("a/b")).id).toBe("a/b");
    expect(fetch.mock.calls[0][0]).toBe("/conversations/a%2Fb");
    expect(imageUrl("x/y")).toBe("/images/x%2Fy");
  });

  it("reports an unreachable server clearly", async () => {
    mockFetch(new TypeError("Failed to fetch"));
    const error = await listConversations().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("network");
  });

  it("keeps string details, validation messages, and has a generic fallback", async () => {
    mockFetch(new Response(JSON.stringify({ detail: "Conversation not found" }), { status: 404 }));
    await expect(deleteConversation("x")).rejects.toMatchObject({ status: 404, message: "Conversation not found" });
    mockFetch(new Response(JSON.stringify({ detail: [{ msg: "String should have at least 1 character" }] }), { status: 422 }));
    await expect(listConversations()).rejects.toMatchObject({ code: "validation" });
    mockFetch(new Response("<html>Bad gateway</html>", { status: 502 }));
    await expect(listConversations()).rejects.toMatchObject({ code: "http_502", message: "Request failed (502)." });
  });

  it("lets aborts through untouched", async () => {
    mockFetch(new DOMException("aborted", "AbortError"));
    await expect(listConversations()).rejects.toMatchObject({ name: "AbortError" });
  });
});
