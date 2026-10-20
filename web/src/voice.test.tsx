// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { VoiceButton } from "./components/VoiceButton";
import { speak, speakable, speechInputAvailable, stopSpeaking } from "./voice";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  delete (window as { SpeechRecognition?: unknown }).SpeechRecognition;
});

class FakeRecognition {
  lang = "";
  continuous = false;
  interimResults = false;
  onresult: ((event: { resultIndex: number; results: { isFinal: boolean; 0: { transcript: string } }[] }) => void) | null = null;
  onerror: (() => void) | null = null;
  onend: (() => void) | null = null;
  start = vi.fn(() => {
    this.onresult?.({ resultIndex: 0, results: [{ isFinal: true, 0: { transcript: "what is 7 times 8" } }] });
  });
  stop = vi.fn();
}

describe("speakable", () => {
  it("drops fenced code and keeps the words around it", () => {
    expect(speakable("The answer is 12.\n\n```python\nprint(1)\n```\nDone.")).toBe("The answer is 12. Done.");
  });
});

describe("VoiceButton", () => {
  it("is hidden when the browser has no speech recognition", () => {
    expect(speechInputAvailable()).toBe(false);
    render(<VoiceButton disabled={false} onTranscript={() => {}} />);
    expect(screen.queryByRole("button", { name: "Speak" })).toBeNull();
  });

  it("puts the final transcript in the draft", () => {
    (window as unknown as { SpeechRecognition: typeof FakeRecognition }).SpeechRecognition = FakeRecognition;
    const onTranscript = vi.fn();
    render(<VoiceButton disabled={false} onTranscript={onTranscript} />);
    fireEvent.click(screen.getByRole("button", { name: "Speak" }));
    expect(onTranscript).toHaveBeenCalledWith("what is 7 times 8");
  });
});

describe("speech output", () => {
  it("speaks a voice reply and can be stopped", () => {
    const speakMock = vi.fn();
    const cancel = vi.fn();
    vi.stubGlobal("speechSynthesis", { speak: speakMock, cancel });
    vi.stubGlobal("SpeechSynthesisUtterance", class {
      text: string;
      onend: (() => void) | null = null;
      constructor(text: string) { this.text = text; }
    });
    speak("The answer is 12.\n\n```python\nprint(1)\n```");
    expect(speakMock.mock.calls[0][0].text).toBe("The answer is 12.");
    stopSpeaking();
    expect(cancel).toHaveBeenCalled();
  });
});
