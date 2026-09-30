// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_BASE_URL } from "../api";
import { KeyDialog } from "./KeyDialog";
import { Sidebar } from "./Sidebar";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function fill(key: string) {
  fireEvent.change(screen.getByLabelText("API key"), { target: { value: key } });
  fireEvent.click(screen.getByRole("button", { name: "Connect" }));
}

describe("KeyDialog", () => {
  it("checks the key against /whoami, then saves", async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ model: "claude-opus-5-5" })));
    vi.stubGlobal("fetch", fetch);
    const onSave = vi.fn();
    render(<KeyDialog initial={null} onSave={onSave} />);

    expect(screen.getByLabelText("API address")).toHaveProperty("value", DEFAULT_BASE_URL);
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull(); // first run: must connect
    fill("  my-key  ");
    await waitFor(() => expect(onSave).toHaveBeenCalledWith({ baseUrl: DEFAULT_BASE_URL, apiKey: "my-key" }));
    expect((fetch.mock.calls[0] as unknown as [string])[0]).toBe(`${DEFAULT_BASE_URL}/whoami`);
  });

  it("explains a rejected key and does not save", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "Invalid or missing X-mX-Key" }), { status: 401 })));
    const onSave = vi.fn();
    render(<KeyDialog initial={null} onSave={onSave} />);
    fill("wrong");
    await screen.findByText(/That key was rejected/);
    expect(onSave).not.toHaveBeenCalled();
  });

  it("shows connection errors and offers Cancel when already configured", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    }));
    const onCancel = vi.fn();
    render(<KeyDialog initial={{ baseUrl: "http://x.test", apiKey: "k" }} onSave={vi.fn()} onCancel={onCancel} />);
    fill("k");
    await screen.findByText(/Can't reach the mX API/);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalled();
  });
});

describe("Sidebar", () => {
  const conversations = [
    { id: "c1", title: "Integration by parts", created_at: "", updated_at: new Date().toISOString() },
    { id: "c2", title: "React state", created_at: "", updated_at: new Date().toISOString() },
  ];

  it("lists conversations and wires select, new, delete, and settings", () => {
    const handlers = { onSelect: vi.fn(), onNew: vi.fn(), onDelete: vi.fn(), onSettings: vi.fn() };
    render(<Sidebar conversations={conversations} activeId="c2" open={false} {...handlers} />);

    fireEvent.click(screen.getByText("Integration by parts"));
    fireEvent.click(screen.getByRole("button", { name: "New chat" }));
    fireEvent.click(screen.getByRole("button", { name: 'Delete "React state"' }));
    fireEvent.click(screen.getByRole("button", { name: "Connection" }));

    expect(handlers.onSelect).toHaveBeenCalledWith("c1");
    expect(handlers.onNew).toHaveBeenCalled();
    expect(handlers.onDelete).toHaveBeenCalledWith(conversations[1]);
    expect(handlers.onSettings).toHaveBeenCalled();
    expect(screen.getByText("React state").closest(".conversation")?.className).toContain("active");
    expect(screen.getAllByText("just now")).toHaveLength(2);
  });

  it("shows an empty state", () => {
    render(<Sidebar conversations={[]} activeId={null} open={false} onSelect={vi.fn()} onNew={vi.fn()} onDelete={vi.fn()} onSettings={vi.fn()} />);
    expect(screen.getByText("No conversations yet.")).toBeTruthy();
  });
});
