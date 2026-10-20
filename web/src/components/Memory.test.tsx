// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { UiMessage } from "../types";
import { MemoryPanel } from "./MemoryPanel";
import { MemorySuggestion } from "./MemorySuggestion";
import { MessageView } from "./MessageView";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("MemorySuggestion", () => {
  const suggestion = { suggestion_id: "s1", text: "Rio is taking Calc II.", conversationId: "c1" };

  it("saves, dismisses, and explains a full list or a duplicate", async () => {
    const calls: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_path: string, init: RequestInit = {}) => {
      calls.push(JSON.parse(String(init.body)));
      return json({ id: "m1", text: suggestion.text, source_conversation_id: "c1", created_at: "", updated_at: "" }, 201);
    }));
    const onDismiss = vi.fn();
    render(<MemorySuggestion suggestion={suggestion} onDismiss={onDismiss} />);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText(/Saved/);
    expect(calls[0]).toEqual({ text: suggestion.text, source_conversation_id: "c1" });

    cleanup();
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: { code: "memory_limit", message: "full" } }, 409)));
    render(<MemorySuggestion suggestion={suggestion} onDismiss={onDismiss} />);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText(/Memory page/);

    cleanup();
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: { code: "memory_duplicate", message: "dup" } }, 409)));
    render(<MemorySuggestion suggestion={suggestion} onDismiss={onDismiss} />);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText(/already in your memories/);

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onDismiss).toHaveBeenCalledWith("s1");
  });
});

describe("MemoryPanel", () => {
  it("lists, edits, deletes, and adds, and says notes are sent with every message", async () => {
    let memories = [{ id: "m1", text: "Rio prefers Python.", source_conversation_id: null, created_at: "", updated_at: "" }];
    vi.stubGlobal("fetch", vi.fn(async (_path: string, init: RequestInit = {}) => {
      if (init.method === "POST") {
        memories = [...memories, { id: "m2", text: "Rio is taking Calc II.", source_conversation_id: null, created_at: "", updated_at: "" }];
        return json(memories[1], 201);
      }
      if (init.method === "PATCH") {
        memories = [{ ...memories[0], text: "Rio prefers Python 3." }];
        return json(memories[0]);
      }
      if (init.method === "DELETE") {
        memories = [];
        return new Response(null, { status: 204 });
      }
      return json(memories);
    }));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<MemoryPanel onClose={() => {}} />);
    expect(await screen.findByText(/sent to the model with every message/)).toBeTruthy();
    expect(screen.getByText("Rio prefers Python.")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText("Edit memory"), { target: { value: "Rio prefers Python 3." } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText("Rio prefers Python 3.");

    fireEvent.change(screen.getByLabelText("Add a note"), { target: { value: "Rio is taking Calc II." } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    await screen.findByText("Rio is taking Calc II.");

    fireEvent.click(screen.getAllByRole("button", { name: "Delete" })[0]);
    await waitFor(() => expect(screen.queryByText("Rio prefers Python 3.")).toBeNull());
  });
});

describe("MessageView memory card", () => {
  it("shows a suggestion under the answer", () => {
    const message: UiMessage = {
      id: "a", role: "assistant", content: "Noted.", images: [], imageRefs: [],
      suggestions: [{ suggestion_id: "s1", text: "Rio is taking Calc II." }],
    };
    render(<MessageView message={message} onDismissMemory={() => {}} />);
    expect(screen.getByText(/Remember: Rio is taking Calc II/)).toBeTruthy();
  });
});
