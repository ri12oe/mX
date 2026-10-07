// @vitest-environment jsdom
// Budget banner, cost panel, and budget helpers (design.md §16). No network.
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cacheShare, monthName, percent, percentUsed, resetDate, shiftMonth, usdLimit } from "../budget";
import type { Budget, UsageSummary } from "../types";
import { BudgetBanner } from "./BudgetBanner";
import { CostPanel } from "./CostPanel";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const budget = (state: Budget["state"], spent: number): Budget =>
  ({ state, spent_usd: spent, limit_usd: 20, resets_at: "2026-11-01T00:00:00-04:00" });

function banner(b: Budget | null, extra: Partial<Parameters<typeof BudgetBanner>[0]> = {}) {
  const handlers = { onToggleOverride: vi.fn(), onDismissWarning: vi.fn() };
  render(<BudgetBanner budget={b} overrideArmed={false} warningDismissed={false} {...handlers} {...extra} />);
  return handlers;
}

describe("BudgetBanner", () => {
  it("shows nothing when the budget is fine or unknown", () => {
    banner(budget("ok", 3));
    banner(null);
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("warns at 80% and can be dismissed for the session", () => {
    const h = banner(budget("warning", 16.4));
    const status = screen.getByRole("status");
    expect(status.textContent).toContain("$16.40 of this month's $20 used");
    expect(status.textContent).toContain("Nov 1");
    fireEvent.click(screen.getByRole("button", { name: "Dismiss budget warning" }));
    expect(h.onDismissWarning).toHaveBeenCalled();
  });

  it("stays hidden once the warning was dismissed", () => {
    banner(budget("warning", 17), { warningDismissed: true });
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("at the limit explains brief mode and offers a one-message override", () => {
    const h = banner(budget("brief", 20.12));
    expect(screen.getByRole("status").textContent).toContain("Brief mode, tools off until Nov 1");
    const button = screen.getByRole("button", { name: "Full answer for this message" });
    expect(button.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(button);
    expect(h.onToggleOverride).toHaveBeenCalled();
  });

  it("shows when the override is armed", () => {
    banner(budget("brief", 21), { overrideArmed: true });
    expect(screen.getByRole("button", { name: /Next message: full answer/ }).getAttribute("aria-pressed")).toBe("true");
  });
});

const SUMMARY: UsageSummary = {
  month: "2026-10", limit_usd: 20, spent_usd: 0.61, state: "ok", resets_at: "2026-11-01T00:00:00-04:00",
  totals: {
    replies: 12, failed_turns: 1, input_tokens: 3400, output_tokens: 21000, cache_read_tokens: 48000,
    cache_write_tokens: 6000, web_searches: 3, code_runs: 2, cache_hit_rate: 0.8366, unknown_cost_replies: 0,
  },
  days: [
    { date: "2026-10-04", cost_usd: 0.18, replies: 1, web_searches: 0, code_runs: 0, cache_hit_rate: 0 },
    { date: "2026-10-06", cost_usd: 0.43, replies: 11, web_searches: 3, code_runs: 2, cache_hit_rate: 0.91 },
  ],
};

function stubSummaries(byMonth: Record<string, UsageSummary>) {
  const fetchMock = vi.fn(async (path: string) => {
    const month = new URL(path, "http://x").searchParams.get("month") ?? "2026-10";
    const body = byMonth[month] ?? { ...SUMMARY, month, spent_usd: 0, days: [] };
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("CostPanel", () => {
  it("shows the month total, one bar per day, and totals", async () => {
    stubSummaries({ "2026-10": SUMMARY });
    render(<CostPanel onClose={() => {}} />);
    const dialog = await screen.findByRole("dialog", { name: "Cost" });
    await within(dialog).findByText("$0.61");
    expect(within(dialog).getByText("On track")).toBeTruthy();
    expect(within(dialog).getByRole("meter").getAttribute("aria-valuenow")).toBe("3");

    const rows = within(within(dialog).getByRole("table")).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(rows[1].textContent).toContain("$0.43");
    expect(rows[1].textContent).toContain("91%");
    const bars = dialog.querySelectorAll<HTMLElement>(".cost-day-bar");
    expect(bars[1].style.width).toBe("100%"); // the biggest day fills the track
    expect(Number.parseFloat(bars[0].style.width)).toBeCloseTo((0.18 / 0.43) * 100, 1);

    const totals = within(dialog).getByRole("region", { name: "Month totals" });
    expect(within(totals).getByText("48,000")).toBeTruthy();
    expect(within(totals).getByText("84%")).toBeTruthy();
  });

  it("moves between months but not past this one", async () => {
    const fetchMock = stubSummaries({ "2026-10": SUMMARY });
    render(<CostPanel onClose={() => {}} />);
    await screen.findByText("$0.61");
    expect(screen.getByRole("button", { name: "Next month" })).toHaveProperty("disabled", true);

    fireEvent.click(screen.getByRole("button", { name: "Previous month" }));
    await screen.findByText("No usage this month.");
    expect(String(fetchMock.mock.calls.at(-1)?.[0])).toBe("/usage/summary?month=2026-09");
    expect(screen.getByRole("button", { name: "Next month" })).toHaveProperty("disabled", false);
  });

  it("closes with the button, Escape, or a click outside", async () => {
    stubSummaries({ "2026-10": SUMMARY });
    const onClose = vi.fn();
    render(<CostPanel onClose={onClose} />);
    await screen.findByText("$0.61");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.click(screen.getByRole("presentation"));
    expect(onClose).toHaveBeenCalledTimes(3);
  });

  it("reports a load error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "boom" }), { status: 500 })));
    render(<CostPanel onClose={() => {}} />);
    expect((await screen.findByRole("alert")).textContent).toContain("boom");
  });
});

describe("budget helpers", () => {
  it("formats and computes", () => {
    expect(percentUsed({ spent_usd: 5, limit_usd: 20 })).toBe(25);
    expect(percentUsed({ spent_usd: 30, limit_usd: 20 })).toBe(100);
    expect(resetDate("2026-11-01T00:00:00-04:00")).toBe(new Date(2026, 10, 1).toLocaleDateString(undefined, { month: "short", day: "numeric" }));
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(monthName("2026-10")).toContain("2026");
    expect(usdLimit(20)).toBe("$20");
    expect(usdLimit(0.6)).toBe("$0.60"); // not rounded to "$1"
    expect(usdLimit(12.5)).toBe("$12.50");
    expect(percent(null)).toBe("—");
    expect(percent(0.836)).toBe("84%");
  });

  it("cache share needs the server's cache numbers", () => {
    expect(cacheShare({ model: "m", input_tokens: 10, output_tokens: 1, cost_usd: 0 })).toBeNull();
    expect(cacheShare({ model: "m", input_tokens: 0, output_tokens: 1, cost_usd: 0, cache_read_tokens: 0, cache_write_tokens: 0 })).toBeNull();
    expect(cacheShare({ model: "m", input_tokens: 20, output_tokens: 1, cost_usd: 0, cache_read_tokens: 60, cache_write_tokens: 20 })).toBe(0.6);
  });
});
