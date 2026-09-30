import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, deleteConversation, listConversations, streamChat, type ApiConfig } from "./api";
import type { ChatEvent } from "./types";

const config: ApiConfig = { baseUrl: "http://api.test/", apiKey: "secret-key" };

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
  const fn = vi.fn(async () => {
    if (response instanceof Error) throw response;
    return response;
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("streamChat", () => {
  it("posts the request with the key and emits typed events", async () => {
    const fetch = mockFetch(
      sseResponse([
        'event: meta\ndata: {"conversation_id": "c1", "message_id": "m1"}\n\nevent: delta\ndata: {"text": "The answer ',
        'is 12."}\n\nevent: done\ndata: {"usage": {"model": "claude-opus-5-5", "input_tokens": 5, "output_tokens": 3, "cost_usd": 0.0001}, "stop_reason": "end_turn"}\n\n',
      ]),
    );
    const events: ChatEvent[] = [];
    await streamChat(config, { message: "4 x 3?", mode: "brief" }, (e) => events.push(e));

    const [calledUrl, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(calledUrl).toBe("http://api.test/chat");
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({ "X-mX-Key": "secret-key", "Content-Type": "application/json" });
    expect(JSON.parse(String(init.body))).toEqual({ message: "4 x 3?", mode: "brief" });

    expect(events.map((e) => e.type)).toEqual(["meta", "delta", "done"]);
    expect(events[1]).toEqual({ type: "delta", text: "The answer is 12." });
    expect(events[2]).toMatchObject({ type: "done", stop_reason: "end_turn", usage: { cost_usd: 0.0001 } });
  });

  it("passes mid-stream error events through", async () => {
    mockFetch(sseResponse(['event: meta\ndata: {"conversation_id": "c", "message_id": "m"}\n\n',
      'event: error\ndata: {"code": "provider_unavailable", "message": "lost"}\n\n']));
    const events: ChatEvent[] = [];
    await streamChat(config, { message: "hi", mode: "normal" }, (e) => events.push(e));
    expect(events[1]).toEqual({ type: "error", code: "provider_unavailable", message: "lost" });
  });

  it("turns an HTTP error with {code, message} into ApiError", async () => {
    mockFetch(new Response(JSON.stringify({ detail: { code: "invalid_image", message: "Image 1 is empty." } }), { status: 422 }));
    await expect(streamChat(config, { message: "hi", mode: "normal" }, () => {})).rejects.toMatchObject({
      name: "ApiError", status: 422, code: "invalid_image", message: "Image 1 is empty.",
    });
  });
});

describe("request errors", () => {
  it("reports an unreachable server clearly", async () => {
    mockFetch(new TypeError("Failed to fetch"));
    const error = await listConversations(config).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("network");
  });

  it("keeps string details and validation messages", async () => {
    mockFetch(new Response(JSON.stringify({ detail: "Conversation not found" }), { status: 404 }));
    await expect(deleteConversation(config, "x")).rejects.toMatchObject({ status: 404, message: "Conversation not found" });

    mockFetch(new Response(JSON.stringify({ detail: [{ msg: "String should have at least 1 character" }] }), { status: 422 }));
    await expect(listConversations(config)).rejects.toMatchObject({ code: "validation" });
  });

  it("lets aborts through untouched", async () => {
    mockFetch(new DOMException("aborted", "AbortError"));
    await expect(listConversations(config)).rejects.toMatchObject({ name: "AbortError" });
  });

  it("escapes ids in paths", async () => {
    const fetch = mockFetch(new Response(null, { status: 204 }));
    await deleteConversation(config, "a/b");
    expect((fetch.mock.calls[0] as unknown as [string])[0]).toBe("http://api.test/conversations/a%2Fb");
  });
});
