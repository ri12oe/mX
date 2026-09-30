// Client for the mX API. Every call sends the X-mX-Key header.
import { SSEParser } from "./sse";
import type { ChatEvent, ChatRequest, ConversationDetail, ConversationSummary } from "./types";

export interface ApiConfig {
  baseUrl: string;
  apiKey: string;
}

export const DEFAULT_BASE_URL = "http://127.0.0.1:8000";

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

function url(config: ApiConfig, path: string): string {
  return config.baseUrl.replace(/\/+$/, "") + path;
}

async function request(config: ApiConfig, path: string, init: RequestInit = {}): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(url(config, path), {
      ...init,
      headers: { "X-mX-Key": config.apiKey, ...init.headers },
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, "network", `Can't reach the mX API at ${config.baseUrl}. Is the server running?`);
  }
  if (!response.ok) throw await toApiError(response);
  return response;
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

export async function checkConnection(config: ApiConfig): Promise<{ model: string }> {
  return (await request(config, "/whoami")).json();
}

export async function listConversations(config: ApiConfig): Promise<ConversationSummary[]> {
  return (await request(config, "/conversations?limit=100")).json();
}

export async function getConversation(config: ApiConfig, id: string): Promise<ConversationDetail> {
  return (await request(config, `/conversations/${encodeURIComponent(id)}`)).json();
}

export async function deleteConversation(config: ApiConfig, id: string): Promise<void> {
  await request(config, `/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
}

/** Stored images need the key header, so they're fetched and shown as object URLs. */
export async function fetchImageUrl(config: ApiConfig, id: string): Promise<string> {
  const blob = await (await request(config, `/images/${encodeURIComponent(id)}`)).blob();
  return URL.createObjectURL(blob);
}

/**
 * POST /chat and call onEvent for each streamed event (meta, delta..., done | error).
 * Throws ApiError for failures before streaming starts. Abort via `signal`:
 * the server then saves nothing (design.md §5).
 */
export async function streamChat(
  config: ApiConfig,
  body: ChatRequest,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await request(config, "/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.body) throw new ApiError(0, "no_stream", "The server returned no stream.");

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  const parser = new SSEParser();
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    for (const message of parser.push(value)) {
      onEvent({ type: message.event, ...JSON.parse(message.data) } as ChatEvent);
    }
  }
}
