// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LoginDialog } from "./LoginDialog";
import { Sidebar } from "./Sidebar";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function signIn(password: string) {
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("LoginDialog", () => {
  it("posts the password and reports success", async () => {
    const fetch = vi.fn(async (_url: string, _init?: RequestInit) => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetch);
    const onSignedIn = vi.fn();
    render(<LoginDialog onSignedIn={onSignedIn} />);

    expect(screen.getByRole("button", { name: "Sign in" })).toHaveProperty("disabled", true); // empty
    signIn("correct horse battery");
    await waitFor(() => expect(onSignedIn).toHaveBeenCalled());
    expect(fetch.mock.calls[0][0]).toBe("/auth/login");
    expect(screen.getByLabelText("Password")).toHaveProperty("value", ""); // cleared
  });

  it("shows the server's message for a wrong password or lockout", async () => {
    const onSignedIn = vi.fn();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: { code: "wrong_password", message: "Wrong password." } }), { status: 401 })));
    render(<LoginDialog onSignedIn={onSignedIn} />);
    signIn("nope-nope-nope");
    await screen.findByText("Wrong password.");

    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: { code: "too_many_attempts", message: "Too many wrong passwords. Try again in 15 minutes." } }), { status: 429 })));
    signIn("again-again-again");
    await screen.findByText(/Try again in 15 minutes/);
    expect(onSignedIn).not.toHaveBeenCalled();
  });

  it("explains a network failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    }));
    render(<LoginDialog onSignedIn={vi.fn()} />);
    signIn("whatever-password");
    await screen.findByText(/Can't reach mX/);
  });
});

describe("Sidebar", () => {
  const conversations = [
    { id: "c1", title: "Integration by parts", created_at: "", updated_at: new Date().toISOString() },
    { id: "c2", title: "React state", created_at: "", updated_at: new Date().toISOString() },
  ];

  it("lists conversations and wires select, new, delete, and sign out", () => {
    const handlers = { onSelect: vi.fn(), onNew: vi.fn(), onDelete: vi.fn(), onSignOut: vi.fn() };
    render(<Sidebar conversations={conversations} activeId="c2" open={false} {...handlers} />);

    fireEvent.click(screen.getByText("Integration by parts"));
    fireEvent.click(screen.getByRole("button", { name: "New chat" }));
    fireEvent.click(screen.getByRole("button", { name: 'Delete "React state"' }));
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    expect(handlers.onSelect).toHaveBeenCalledWith("c1");
    expect(handlers.onNew).toHaveBeenCalled();
    expect(handlers.onDelete).toHaveBeenCalledWith(conversations[1]);
    expect(handlers.onSignOut).toHaveBeenCalled();
    expect(screen.getByText("React state").closest(".conversation")?.className).toContain("active");
    expect(screen.getAllByText("just now")).toHaveLength(2);
  });

  it("shows an empty state", () => {
    render(<Sidebar conversations={[]} activeId={null} open={false} onSelect={vi.fn()} onNew={vi.fn()} onDelete={vi.fn()} onSignOut={vi.fn()} />);
    expect(screen.getByText("No conversations yet.")).toBeTruthy();
  });
});
