// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LoginDialog } from "./LoginDialog";

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
