// Small helpers for showing the monthly budget (design.md §16).
import type { Budget, BudgetState, Usage } from "./types";

export const BUDGET_LABELS: Record<BudgetState, string> = {
  ok: "On track",
  warning: "Warning",
  brief: "Limit reached",
};

export const usd = (value: number, digits = 2): string => `$${value.toFixed(digits)}`;

/** A limit as people say it: "$20", but "$0.60" or "$12.50" when it isn't whole dollars. */
export const usdLimit = (value: number): string => usd(value, Number.isInteger(value) ? 0 : 2);

/** Share of the limit used, 0–100 (capped, for bar widths). */
export function percentUsed(budget: Pick<Budget, "spent_usd" | "limit_usd">): number {
  return Math.min(100, Math.max(0, (budget.spent_usd / budget.limit_usd) * 100));
}

/** "Nov 1" from the server's `resets_at` (the next local month's start). */
export function resetDate(resetsAt: string): string {
  const [year, month, day] = resetsAt.slice(0, 10).split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** Share of a reply's prompt read from the cache, or null when the server didn't report it. */
export function cacheShare(usage: Usage): number | null {
  if (usage.cache_read_tokens === undefined) return null;
  const total = usage.input_tokens + usage.cache_read_tokens + (usage.cache_write_tokens ?? 0);
  return total ? usage.cache_read_tokens / total : null;
}

export const percent = (share: number | null): string => (share === null ? "—" : `${Math.round(share * 100)}%`);

/** "2026-10" ± n months. */
export function shiftMonth(month: string, by: number): string {
  const [year, m] = month.split("-").map(Number);
  const date = new Date(year, m - 1 + by, 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

/** "October 2026" for "2026-10". */
export function monthName(month: string): string {
  const [year, m] = month.split("-").map(Number);
  return new Date(year, m - 1, 1).toLocaleDateString(undefined, { month: "long", year: "numeric" });
}
