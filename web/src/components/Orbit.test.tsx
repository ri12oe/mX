// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ConversationSummary } from "../types";
import { HistoryPanel } from "./HistoryPanel";
import { DIAL, dialHeight, MAX_SPOKES, OrbitDial, spokeGeometry } from "./OrbitDial";

afterEach(cleanup);

const convo = (i: number): ConversationSummary => ({
  id: `c${i}`,
  title: `Chat number ${i}`,
  created_at: "",
  updated_at: new Date().toISOString(),
});
const many = Array.from({ length: 8 }, (_, i) => convo(i + 1));

function dialHandlers() {
  return { onSelect: vi.fn(), onNew: vi.fn(), onOpenHistory: vi.fn() };
}

describe("OrbitDial", () => {
  it("shows the most recent chats on spokes, plus All chats with the total", () => {
    render(<OrbitDial conversations={many} activeId="c2" {...dialHandlers()} />);
    const dial = screen.getByRole("complementary", { name: "Conversations" });
    for (let i = 1; i <= MAX_SPOKES; i++) expect(within(dial).getByText(`Chat number ${i}`)).toBeTruthy();
    expect(within(dial).queryByText("Chat number 6")).toBeNull(); // older ones live in history
    expect(within(dial).getByRole("button", { name: "All chats" }).textContent).toBe("All chats · 8");
    expect(within(dial).getByText("Chat number 2").className).toContain("active");
    expect(within(dial).getByText("Chat number 1").getAttribute("title")).toBe("Chat number 1");
  });

  it("wires New, a spoke, and All chats", () => {
    const handlers = dialHandlers();
    render(<OrbitDial conversations={many.slice(0, 2)} activeId={null} {...handlers} />);
    fireEvent.click(screen.getByRole("button", { name: "New chat" }));
    fireEvent.click(screen.getByText("Chat number 2"));
    fireEvent.click(screen.getByRole("button", { name: "All chats" }));
    expect(handlers.onNew).toHaveBeenCalled();
    expect(handlers.onSelect).toHaveBeenCalledWith("c2");
    expect(handlers.onOpenHistory).toHaveBeenCalled();
  });

  it("still offers All chats when there are none", () => {
    render(<OrbitDial conversations={[]} activeId={null} {...dialHandlers()} />);
    expect(screen.getByRole("button", { name: "All chats" }).textContent).toBe("All chats · 0");
  });
});

describe("spoke geometry", () => {
  it("spaces label rows evenly around the dial's center", () => {
    const height = dialHeight(5);
    const rows = spokeGeometry(5, height).map((g) => g.y);
    expect(rows[2]).toBe(height / 2); // middle row on the center line
    expect(rows[1] - rows[0]).toBe(DIAL.spacing);
  });

  it("leaves the ring on the circle and lines labels up in one column", () => {
    const geometry = spokeGeometry(4, dialHeight(4));
    const cy = dialHeight(4) / 2;
    for (const g of geometry) {
      const [x, y] = g.edge;
      expect(Math.hypot(x - DIAL.center, y - cy)).toBeCloseTo(DIAL.radius, 5);
      expect(g.elbow[1]).toBe(g.y); // bends to horizontal at the label row
      expect(g.end[0]).toBe(geometry[0].end[0]);
    }
  });
});

describe("HistoryPanel", () => {
  function setup() {
    const handlers = { onSelect: vi.fn(), onNew: vi.fn(), onDelete: vi.fn(), onClose: vi.fn() };
    render(<HistoryPanel conversations={many} activeId="c3" {...handlers} />);
    return handlers;
  }

  it("lists every chat, with search", () => {
    setup();
    const dialog = screen.getByRole("dialog", { name: "All chats" });
    expect(within(dialog).getAllByRole("listitem")).toHaveLength(8);
    fireEvent.change(screen.getByLabelText("Search chats"), { target: { value: "number 7" } });
    expect(within(dialog).getAllByRole("listitem")).toHaveLength(1);
    fireEvent.change(screen.getByLabelText("Search chats"), { target: { value: "zzz" } });
    expect(screen.getByText("No chats match.")).toBeTruthy();
  });

  it("opens, deletes, starts new, and closes (button, Escape, backdrop)", () => {
    const h = setup();
    fireEvent.click(screen.getByText("Chat number 4"));
    fireEvent.click(screen.getByRole("button", { name: 'Delete "Chat number 5"' }));
    fireEvent.click(screen.getByRole("button", { name: "+ Start new chat" }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.click(screen.getByRole("presentation"));
    expect(h.onSelect).toHaveBeenCalledWith("c4");
    expect(h.onDelete).toHaveBeenCalledWith(many[4]);
    expect(h.onNew).toHaveBeenCalled();
    expect(h.onClose).toHaveBeenCalledTimes(3);
  });

  it("highlights the open chat and doesn't close when clicking inside", () => {
    const h = setup();
    expect(screen.getByText("Chat number 3").closest("li")?.className).toContain("active");
    fireEvent.click(screen.getByRole("dialog", { name: "All chats" }));
    expect(h.onClose).not.toHaveBeenCalled();
  });
});
