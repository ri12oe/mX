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
  // Phase 2 (design.md §5); optional so older payloads still parse.
  cache_read_tokens?: number;
  cache_write_tokens?: number;
  web_searches?: number;
  code_runs?: number;
}

/** The month's budget (design.md §16). `forced` = this turn was switched to brief mode. */
export type BudgetState = "ok" | "warning" | "brief";

export interface Budget {
  state: BudgetState;
  spent_usd: number;
  limit_usd: number;
  resets_at: string; // next local month's start, ISO with offset
  month?: string; // "2026-10" (GET /usage/budget)
  forced?: boolean; // in chat events only
}

/** One Server-Sent Event from POST /chat. */
export type ChatEvent =
  | { type: "meta"; conversation_id: string; message_id: string; mode?: Mode; tools?: boolean; budget?: Budget }
  | { type: "delta"; text: string }
  | { type: "done"; usage: Usage; stop_reason: string; budget?: Budget }
  | { type: "error"; code: string; message: string };

export interface ChatRequest {
  message: string;
  mode: Mode;
  conversation_id?: string;
  images?: string[]; // base64 or data: URLs
  budget_override?: boolean; // run this one message as requested even when the budget is used up
}

/** GET /usage/summary (design.md §16). */
export interface UsageTotals {
  replies: number;
  failed_turns: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  web_searches: number;
  code_runs: number;
  cache_hit_rate: number | null;
  unknown_cost_replies: number;
}

export interface UsageDay {
  date: string; // local date, "2026-10-04"
  cost_usd: number;
  replies: number;
  web_searches: number;
  code_runs: number;
  cache_hit_rate: number | null;
}

export interface UsageSummary {
  month: string;
  limit_usd: number;
  spent_usd: number;
  state: BudgetState;
  resets_at: string;
  totals: UsageTotals;
  days: UsageDay[];
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
