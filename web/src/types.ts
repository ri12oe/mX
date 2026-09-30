// Shapes of the mX API (docs/design.md §5).

export type Mode = "normal" | "brief";

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface StoredMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  image_refs: string[];
  created_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: StoredMessage[];
}

export interface Usage {
  model: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
}

/** One Server-Sent Event from POST /chat. */
export type ChatEvent =
  | { type: "meta"; conversation_id: string; message_id: string }
  | { type: "delta"; text: string }
  | { type: "done"; usage: Usage; stop_reason: string }
  | { type: "error"; code: string; message: string };

export interface ChatRequest {
  message: string;
  mode: Mode;
  conversation_id?: string;
  images?: string[]; // base64 or data: URLs
}

/** A message as the UI shows it (stored or in progress). */
export interface UiMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  images: string[]; // data: URLs for new uploads
  imageRefs: string[]; // stored image ids, loaded via GET /images/{id}
  usage?: Usage;
  stopReason?: string;
  error?: string;
  streaming?: boolean;
}
