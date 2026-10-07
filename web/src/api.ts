// Client for the mX API. The web app is served from the same origin as the API
// (in development, Vite proxies the API paths), so requests carry the HttpOnly
// session cookie automatically; no key is ever stored in the browser.
import { SSEParser } from "./sse";
import type { Budget, ChatEvent, ChatRequest, ConversationDetail, ConversationSummary, UsageSummary } from "./types";

/** An HTTP error from the API, with its machine-readable code when there is one. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(path, { credentials: "same-origin", ...init });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, "network", "Can't reach mX. Check your connection or that the server is running.");
  }
  if (!response.ok) throw await toApiError(response);
  return response;
}

function postJson(path: string, body: unknown, signal?: AbortSignal): Promise<Response> {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
}

/** FastAPI errors look like {detail: "text"} or {detail: {code, message}} or {detail: [validation...]}. */
async function toApiError(response: Response): Promise<ApiError> {
  let detail: unknown;
  try {
    detail = (await response.json()).detail;
  } catch {
    detail = undefined;
  }
  if (detail && typeof detail === "object" && "code" in detail && "message" in detail) {
    const { code, message } = detail as { code: string; message: string };
    return new ApiError(response.status, code, message);
  }
  if (typeof detail === "string") return new ApiError(response.status, `http_${response.status}`, detail);
  if (Array.isArray(detail) && detail[0]?.msg) {
    return new ApiError(response.status, "validation", String(detail[0].msg));
  }
  return new ApiError(response.status, `http_${response.status}`, `Request failed (${response.status}).`);
}

export const isSignedOut = (err: unknown): boolean => err instanceof ApiError && err.status === 401;

/** Resolves if the session cookie is valid; throws ApiError(401) if not. */
export async function whoami(): Promise<{ model: string }> {
  return (await request("/whoami")).json();
}

export async function login(password: string): Promise<void> {
  await postJson("/auth/login", { password });
}

export async function logout(): Promise<void> {
  await request("/auth/logout", { method: "POST" });
}

export async function listConversations(): Promise<ConversationSummary[]> {
  return (await request("/conversations?limit=100")).json();
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  return (await request(`/conversations/${encodeURIComponent(id)}`)).json();
}

export async function deleteConversation(id: string): Promise<void> {
  await request(`/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export const imageUrl = (id: string): string => `/images/${encodeURIComponent(id)}`;

/** This month's spend against the limit (design.md §16). */
export async function getBudget(): Promise<Budget> {
  return (await request("/usage/budget")).json();
}

/** Month totals and one row per local day. `month` is "YYYY-MM"; default: this month. */
export async function getUsageSummary(month?: string): Promise<UsageSummary> {
  const query = month ? `?month=${encodeURIComponent(month)}` : "";
  return (await request(`/usage/summary${query}`)).json();
}

/**
 * POST /chat and call onEvent for each streamed event (meta, delta..., done | error).
 * Throws ApiError for failures before streaming starts. Abort via `signal`:
 * the server then saves nothing (design.md §5). ": ping" heartbeats are skipped.
 */
export async function streamChat(
  body: ChatRequest,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await postJson("/chat", body, signal);
  if (!response.body) throw new ApiError(0, "no_stream", "The server returned no stream.");

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  const parser = new SSEParser();
  let finished = false; // saw `done` or `error`
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    for (const message of parser.push(value)) {
      const event = { type: message.event, ...JSON.parse(message.data) } as ChatEvent;
      finished ||= event.type === "done" || event.type === "error";
      onEvent(event);
    }
  }
  if (!finished) throw new ApiError(0, "incomplete", "The reply stopped unexpectedly.");
}
