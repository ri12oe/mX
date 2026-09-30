// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Mode } from "../types";
import { Composer } from "./Composer";

afterEach(cleanup);

function Harness(props: { streaming?: boolean; onSend?: (t: string, i: string[]) => void; onStop?: () => void; onMode?: (m: Mode) => void }) {
  const [text, setText] = useState("");
  const [mode, setMode] = useState<Mode>("normal");
  return (
    <Composer
      text={text}
      onTextChange={setText}
      mode={mode}
      onModeChange={(m) => {
        setMode(m);
        props.onMode?.(m);
      }}
      streaming={props.streaming ?? false}
      onSend={(t, i) => {
        props.onSend?.(t, i);
        setText("");
      }}
      onStop={props.onStop ?? (() => {})}
    />
  );
}

const box = () => screen.getByLabelText("Message") as HTMLTextAreaElement;
const png = (name = "a.png") => new File([new Uint8Array([137, 80, 78, 71])], name, { type: "image/png" });

describe("Composer", () => {
  it("sends the trimmed text on Enter and clears the box", () => {
    const onSend = vi.fn();
    render(<Harness onSend={onSend} />);
    fireEvent.change(box(), { target: { value: "  What is 2 + 2?  " } });
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("What is 2 + 2?", []);
    expect(box().value).toBe("");
  });

  it("does not send on Shift+Enter or when the box is blank", () => {
    const onSend = vi.fn();
    render(<Harness onSend={onSend} />);
    fireEvent.change(box(), { target: { value: "line one" } });
    fireEvent.keyDown(box(), { key: "Enter", shiftKey: true });
    fireEvent.change(box(), { target: { value: "   " } });
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Send" })).toHaveProperty("disabled", true);
  });

  it("shows Stop while streaming and doesn't send", () => {
    const onSend = vi.fn();
    const onStop = vi.fn();
    render(<Harness streaming onSend={onSend} onStop={onStop} />);
    fireEvent.change(box(), { target: { value: "hi" } });
    fireEvent.keyDown(box(), { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Stop generating" }));
    expect(onSend).not.toHaveBeenCalled();
    expect(onStop).toHaveBeenCalledOnce();
  });

  it("switches mode", () => {
    const onMode = vi.fn();
    render(<Harness onMode={onMode} />);
    fireEvent.click(screen.getByRole("radio", { name: "Brief" }));
    expect(onMode).toHaveBeenCalledWith("brief");
    expect(screen.getByRole("radio", { name: "Brief" }).getAttribute("aria-checked")).toBe("true");
  });

  it("attaches images, sends them as data URLs, and lets you remove one", async () => {
    const onSend = vi.fn();
    const { container } = render(<Harness onSend={onSend} />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [png("a.png"), png("b.png")] } });
    await waitFor(() => expect(screen.getAllByAltText(/Image \d to send/)).toHaveLength(2));

    fireEvent.click(screen.getByRole("button", { name: "Remove image 1" }));
    expect(screen.getAllByAltText(/Image \d to send/)).toHaveLength(1);

    fireEvent.change(box(), { target: { value: "What is this?" } });
    fireEvent.keyDown(box(), { key: "Enter" });
    const [, images] = onSend.mock.calls[0] as [string, string[]];
    expect(images).toHaveLength(1);
    expect(images[0]).toMatch(/^data:image\/png;base64,/);
  });

  it("explains rejected files and the 4-image limit", async () => {
    const { container } = render(<Harness />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const pdf = new File(["%PDF"], "notes.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [pdf] } });
    await screen.findByText(/notes\.pdf: only JPEG, PNG, GIF, or WebP/);

    fireEvent.change(input, { target: { files: [png(), png(), png(), png(), png()] } });
    await screen.findByText(/Up to 4 images per message/);
    expect(screen.getAllByAltText(/Image \d to send/)).toHaveLength(4);
  });
});

describe("Composer paste and drop", () => {
  it("attaches an image pasted from the clipboard", async () => {
    render(<Harness />);
    fireEvent.paste(box(), { clipboardData: { files: [png("pasted.png")] } });
    await waitFor(() => expect(screen.getAllByAltText(/Image \d to send/)).toHaveLength(1));
  });

  it("leaves a plain-text paste alone", () => {
    render(<Harness />);
    fireEvent.paste(box(), { clipboardData: { files: [] } });
    expect(screen.queryAllByAltText(/Image \d to send/)).toHaveLength(0);
  });

  it("highlights while dragging and attaches dropped images", async () => {
    const { container } = render(<Harness />);
    const composer = container.querySelector(".composer") as HTMLElement;
    fireEvent.dragOver(composer);
    expect(composer.className).toContain("dragging");
    fireEvent.dragLeave(composer);
    expect(composer.className).not.toContain("dragging");
    fireEvent.drop(composer, { dataTransfer: { files: [png("dropped.png")] } });
    await waitFor(() => expect(screen.getAllByAltText(/Image \d to send/)).toHaveLength(1));
  });
});
