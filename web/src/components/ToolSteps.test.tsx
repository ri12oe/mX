// @vitest-environment jsdom
// Tool step chips, the Tools toggle, and the core state while a tool runs (design.md §17).
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { coreStateFor } from "../App";
import { loadTools, saveTools } from "../settings";
import type { ToolStep, UiMessage } from "../types";
import { Composer } from "./Composer";
import { MessageView } from "./MessageView";
import { stepLabel, ToolSteps } from "./ToolSteps";

afterEach(() => {
  cleanup();
  localStorage.clear();
});

const CODE = "print(2**100)";
const running: ToolStep = { id: "t1", tool: "code_execution", status: "running", input: { code: CODE } };
const ran: ToolStep = { ...running, status: "ok", output: { stdout: "1267650600228229401496703205376\n", stderr: "", return_code: 0 } };

describe("step labels", () => {
  it.each([
    [running, "Running code…"],
    [ran, "Ran code"],
    [{ ...ran, output: { stdout: "", stderr: "ZeroDivisionError", return_code: 1 } }, "Ran code (exit 1)"],
    [{ ...running, status: "error", error_code: "execution_time_exceeded" }, "Code failed: time limit reached"],
    [{ ...running, status: "error", error_code: "something_new" }, "Code failed: something_new"],
    [{ id: "s", tool: "web_search", status: "running", input: { query: "Python 3.14" } }, "Searching: Python 3.14…"],
    [{ id: "s", tool: "web_search", status: "ok", input: { query: "Python 3.14" },
       output: { sources: [{ url: "https://python.org", title: "Python" }] } }, "Searched: Python 3.14 (1 source)"],
    [{ id: "s", tool: "web_search", status: "error", input: { query: "x" }, error_code: "max_uses_exceeded" },
     "Search failed: search limit reached"],
  ] as [ToolStep, string][])("%#: %s", (step, label) => {
    expect(stepLabel(step)).toBe(label);
  });
});

describe("ToolSteps", () => {
  it("expands to show the code and its output as plain text", () => {
    const sneaky: ToolStep = { ...ran, input: { code: "print('**not bold** <b>x</b>')" },
      output: { stdout: "**not bold** <b>x</b>\n", stderr: "warning: careful", return_code: 0 } };
    render(<ToolSteps steps={[sneaky]} />);
    const chip = screen.getByText("Ran code").closest("details")!;
    expect(chip.open).toBe(false);
    fireEvent.click(screen.getByText("Ran code"));
    const blocks = chip.querySelectorAll("pre");
    expect(blocks[0].textContent).toBe("print('**not bold** <b>x</b>')");
    expect(blocks[1].textContent).toBe("**not bold** <b>x</b>\n"); // never rendered as markdown or HTML
    expect(chip.querySelector("strong, b")).toBeNull();
    expect(within(chip).getByText("Errors")).toBeTruthy();
  });

  it("says when stored code or output was cut short", () => {
    render(<ToolSteps steps={[{ ...ran, input: { code: "x", code_truncated: true }, output: { stdout: "y", stdout_truncated: true } }]} />);
    expect(screen.getAllByText("Cut short to keep the chat small.")).toHaveLength(2);
  });

  it("labels bash commands and file edits", () => {
    render(<ToolSteps steps={[{ ...ran, input: { code: "ls", language: "bash" } }]} />);
    expect(screen.getByText("Command")).toBeTruthy();
  });

  it("lists a search's sources as text", () => {
    const search: ToolStep = { id: "s", tool: "web_search", status: "ok", input: { query: "q" },
      output: { sources: [{ url: "https://docs.python.org/3/", title: "Python docs" }] } };
    render(<ToolSteps steps={[search]} />);
    expect(screen.getByText("Python docs")).toBeTruthy();
    expect(screen.getByText("docs.python.org")).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull(); // safe links come with the Sources list (task 17)
  });

  it("marks failed steps and non-zero exits for attention", () => {
    render(<ToolSteps steps={[{ ...running, id: "e", status: "error", error_code: "unavailable" },
      { ...ran, id: "x", output: { stdout: "", stderr: "boom", return_code: 2 } }]} />);
    const chips = document.querySelectorAll("details.tool-step");
    expect([...chips].map((c) => c.className.includes("tool-step-warn"))).toEqual([true, true]);
  });
});

describe("MessageView with steps", () => {
  const base: UiMessage = { id: "a", role: "assistant", content: "", images: [], imageRefs: [] };

  it("shows a running step instead of the thinking dots", () => {
    render(<MessageView message={{ ...base, streaming: true, steps: [running] }} />);
    expect(screen.getByText("Running code…")).toBeTruthy();
    expect(screen.queryByLabelText("mX is thinking")).toBeNull();
  });

  it("shows steps above the answer", () => {
    render(<MessageView message={{ ...base, content: "It is big.", steps: [ran] }} />);
    const body = document.querySelector(".assistant-body")!;
    expect(body.firstElementChild?.className).toBe("tool-steps");
    expect(screen.getByText("It is big.")).toBeTruthy();
  });

  it("says when a long tool session stopped early", () => {
    render(<MessageView message={{ ...base, content: "Partial", stopReason: "pause_turn" }} />);
    expect(screen.getByText(/the answer may be incomplete/)).toBeTruthy();
  });
});

describe("core state", () => {
  const user: UiMessage = { id: "u", role: "user", content: "q", images: [], imageRefs: [] };
  it("thinks while a tool runs, even after some text", () => {
    const msg: UiMessage = { id: "a", role: "assistant", content: "Let me check.", images: [], imageRefs: [], steps: [running] };
    expect(coreStateFor([user, msg], true)).toBe("thinking");
    expect(coreStateFor([user, { ...msg, steps: [ran] }], true)).toBe("streaming");
  });
});

describe("Tools toggle", () => {
  const props = { text: "", onTextChange: () => {}, mode: "normal" as const, onModeChange: () => {},
    streaming: false, onSend: () => {}, onStop: () => {} };

  it("toggles and reports the new state", () => {
    const onToolsChange = vi.fn();
    render(<Composer {...props} tools onToolsChange={onToolsChange} />);
    const toggle = screen.getByRole("button", { name: /Tools on/ });
    expect(toggle.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(toggle);
    expect(onToolsChange).toHaveBeenCalledWith(false);
  });

  it("is hidden when tools are off server-wide", () => {
    render(<Composer {...props} />);
    expect(screen.queryByRole("button", { name: /Tools/ })).toBeNull();
  });

  it("is remembered in this browser, on by default", () => {
    expect(loadTools()).toBe(true);
    saveTools(false);
    expect(loadTools()).toBe(false);
    saveTools(true);
    expect(loadTools()).toBe(true);
  });
});
