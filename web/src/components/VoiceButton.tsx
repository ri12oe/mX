// Push-to-talk. Hidden when the browser has no speech recognition (design.md §19).
import { useEffect, useState } from "react";
import { speechInputAvailable, startListening, type SpeechRecognizer } from "../voice";

interface Props {
  disabled: boolean;
  onTranscript: (text: string) => void;
  onListeningChange?: (listening: boolean) => void;
  bindToggle?: (toggle: (() => void) | undefined) => void;
}

export function VoiceButton({ disabled, onTranscript, onListeningChange, bindToggle }: Props) {
  const [recognition, setRecognition] = useState<SpeechRecognizer | null>(null);
  const available = speechInputAvailable();
  const listening = recognition !== null;

  function toggle() {
    if (recognition) {
      recognition.stop();
      setRecognition(null);
      return;
    }
    const next = startListening((text) => {
      onTranscript(text);
      setRecognition(null);
    });
    if (!next) return;
    next.onerror = () => setRecognition(null);
    next.onend = () => setRecognition(null);
    setRecognition(next);
  }

  useEffect(() => {
    onListeningChange?.(listening);
  }, [listening, onListeningChange]);

  useEffect(() => {
    if (!available) return;
    bindToggle?.(toggle);
    return () => bindToggle?.(undefined);
  });

  if (!available) return null;

  return (
    <button
      type="button"
      className={`icon-button voice-button${listening ? " active" : ""}`}
      aria-pressed={listening}
      aria-label={listening ? "Stop listening" : "Speak"}
      disabled={disabled}
      onClick={toggle}
    >
      <span aria-hidden="true">{listening ? "●" : "🎤"}</span>
    </button>
  );
}
