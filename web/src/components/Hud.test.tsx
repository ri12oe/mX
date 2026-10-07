// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { coreStateFor } from "../App";
import type { UiMessage } from "../types";
import { arc, Core, CORE_LABELS, type CoreState } from "./Core";
import { Clock, formatCost, StatusPanel } from "./StatusPanel";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const msg = (patch: Partial<UiMessage>): UiMessage => ({
  id: "m", role: "assistant", content: "", images: [], imageRefs: [], ...patch,
});

describe("Core", () => {
  it.each(Object.entries(CORE_LABELS))("%s state is labeled %s for screen readers", (state, label) => {
    const { container } = render(<Core state={state as CoreState} />);
    expect(screen.getByRole("img", { name: `mX core: ${label}` })).toBeTruthy();
    expect(container.firstElementChild?.className).toContain(`core-${state}`);
    expect(screen.getByText(label)).toBeTruthy();
  });

  it("can hide the text label", () => {
    render(<Core state="idle" showLabel={false} />);
    expect(screen.queryByText("Standby")).toBeNull();
  });

  it("draws arcs starting at the top", () => {
    expect(arc(80, 0, 90)).toBe("M 100.00 20.00 A 80 80 0 0 1 180.00 100.00");
    expect(arc(80, 0, 270)).toContain(" 0 1 1 "); // large-arc flag for > 180°
  });
});

describe("coreStateFor", () => {
  it("is idle with nothing happening", () => {
    expect(coreStateFor([], false)).toBe("idle");
    expect(coreStateFor([msg({ content: "done" })], false)).toBe("idle");
  });
  it("thinks before the first words, responds while streaming", () => {
    expect(coreStateFor([msg({ role: "user", content: "q" }), msg({ streaming: true })], true)).toBe("thinking");
    expect(coreStateFor([msg({ content: "partial", streaming: true })], true)).toBe("streaming");
  });
  it("shows a fault after an error, until the next turn", () => {
    expect(coreStateFor([msg({ error: "Lost." })], false)).toBe("error");
    expect(coreStateFor([msg({ error: "Lost." }), msg({ role: "user", content: "again" }), msg({})], true)).toBe("thinking");
  });
});

describe("StatusPanel", () => {
  const base = {
    coreState: "idle" as const,
    model: "claude-opus-5-5",
    lastUsage: null,
    session: { replies: 0, costUsd: 0, unknownCost: false },
    conversationCount: 1,
    mode: "normal" as const,
    budget: null,
    onOpenCost: () => {},
    onSignOut: () => {},
  };

  it.each([
    ["ok", 4.12, "$4.12 / $20.00", "On track", 21],
    ["warning", 16.5, "$16.50 / $20.00", "Warning", 83],
    ["brief", 23, "$23.00 / $20.00", "Limit reached", 100],
  ] as const)("shows the month's %s budget with a labeled bar", (state, spent, text, label, pct) => {
    const onOpenCost = vi.fn();
    const budget = { state, spent_usd: spent, limit_usd: 20, resets_at: "2026-11-01T00:00:00-04:00" };
    render(<StatusPanel {...base} budget={budget} onOpenCost={onOpenCost} />);
    const month = screen.getByRole("region", { name: "Month" });
    expect(within(month).getByText(text)).toBeTruthy();
    expect(within(month).getByText(label)).toBeTruthy(); // never color alone
    expect(within(month).getByRole("meter").getAttribute("aria-valuenow")).toBe(String(pct));
    expect(month.querySelector(`.budget-${state}`)).not.toBeNull();
    fireEvent.click(within(month).getByRole("button", { name: "Cost details" }));
    expect(onOpenCost).toHaveBeenCalled();
  });

  it("shows the last reply's cache share", () => {
    const lastUsage = { model: "m", input_tokens: 100, output_tokens: 5, cost_usd: 0.001,
      cache_read_tokens: 800, cache_write_tokens: 100 };
    render(<StatusPanel {...base} lastUsage={lastUsage} />);
    expect(within(screen.getByRole("region", { name: "Last reply" })).getByText("80%")).toBeTruthy();
  });

  it("shows only real readouts", () => {
    render(<StatusPanel {...base} />);
    const link = screen.getByRole("region", { name: "Link" });
    expect(within(link).getByText("Online")).toBeTruthy();
    expect(within(link).getByText("claude-opus-5-5")).toBeTruthy();
    expect(within(link).getByText("Normal")).toBeTruthy();
    expect(screen.getByText("No replies yet this session.")).toBeTruthy();
    expect(within(screen.getByRole("region", { name: "Session" })).getByText("1 chat")).toBeTruthy();
  });

  it("shows the last reply and session totals", () => {
    render(
      <StatusPanel
        {...base}
        mode="brief"
        lastUsage={{ model: "claude-opus-5-5", input_tokens: 1234, output_tokens: 56, cost_usd: 0.0061 }}
        session={{ replies: 3, costUsd: 0.0184, unknownCost: true }}
        conversationCount={7}
      />,
    );
    const last = screen.getByRole("region", { name: "Last reply" });
    expect(within(last).getByText("1,234")).toBeTruthy();
    expect(within(last).getByText("$0.0061")).toBeTruthy();
    const session = screen.getByRole("region", { name: "Session" });
    expect(within(session).getByText("3")).toBeTruthy();
    expect(within(session).getByText("≥ $0.0184")).toBeTruthy(); // a reply had no price
    expect(within(session).getByText("7 chats")).toBeTruthy();
    expect(screen.getByText("Brief")).toBeTruthy();
  });

  it("says Connecting until the model is known", () => {
    render(<StatusPanel {...base} model={null} />);
    expect(screen.getByText("Connecting")).toBeTruthy();
  });

  it("formats unknown costs", () => {
    expect(formatCost(null)).toBe("unknown");
    expect(formatCost(0.00012)).toBe("$0.0001");
  });
});

describe("Clock", () => {
  it("ticks every second", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 9, 1, 9, 5, 7));
    render(<Clock />);
    const timer = screen.getByRole("timer", { name: "Local time" });
    expect(timer.textContent).toContain("09:05:07");
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(timer.textContent).toContain("09:05:08");
  });
});
